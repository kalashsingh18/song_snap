from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uuid
import os
from datetime import datetime
from pymongo import MongoClient
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="SongSnaps API", version="1.0.0")

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB connection
MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
try:
    client = MongoClient(MONGO_URL)
    db = client.songsnaps
    orders_collection = db.orders
    logger.info("Connected to MongoDB successfully")
except Exception as e:
    logger.error(f"Failed to connect to MongoDB: {e}")
    raise

# Pydantic models
class OrderRequest(BaseModel):
    plan: str  # 'snap', 'snappack', or 'creator'

class OrderResponse(BaseModel):
    orderId: str
    plan: str
    price: str
    timestamp: datetime
    whatsappNumber: str

# Plan pricing and details
PLAN_DETAILS = {
    'snap': {
        'name': 'Snap',
        'price': '$3.99',
        'description': '1 full-length custom song with cover art',
        'delivery': '2 hours',
        'features': ['1 custom song', 'Simple cover art', '2-hour delivery', 'No edits']
    },
    'snappack': {
        'name': 'Snap Pack',
        'price': '$9.99',
        'description': '3 songs over 7 days',
        'delivery': '48 hours each',
        'features': ['3 custom songs', 'Different moods/vibes', 'Cover art for each', '48-hour delivery']
    },
    'creator': {
        'name': 'Creator Pack',
        'price': '$24.99/mo',
        'description': 'Up to 10 songs per month with extras',
        'delivery': 'Priority',
        'features': ['Up to 10 songs/month', 'AI stems', 'Instrumentals', 'TikTok clips', 'Priority delivery']
    }
}

@app.get("/")
async def root():
    return {"message": "SongSnaps API is running", "status": "healthy"}

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Test database connection
        orders_collection.find_one()
        return {
            "status": "healthy",
            "database": "connected",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail="Service unhealthy")

@app.post("/api/generate-order", response_model=OrderResponse)
async def generate_order(order_request: OrderRequest):
    """Generate a unique order ID and store order details"""
    try:
        # Validate plan
        if order_request.plan not in PLAN_DETAILS:
            raise HTTPException(status_code=400, detail="Invalid plan type")
        
        plan_info = PLAN_DETAILS[order_request.plan]
        
        # Generate unique order ID
        order_id = f"SS-{uuid.uuid4().hex[:8].upper()}"
        
        # Create order document
        order_doc = {
            "orderId": order_id,
            "plan": order_request.plan,
            "planName": plan_info['name'],
            "price": plan_info['price'],
            "description": plan_info['description'],
            "delivery": plan_info['delivery'],
            "features": plan_info['features'],
            "timestamp": datetime.now(),
            "status": "payment_confirmed",
            "whatsappNumber": "+1234567890",  # Replace with your actual WhatsApp number
            "fulfilled": False
        }
        
        # Store in database
        result = orders_collection.insert_one(order_doc)
        
        if not result.inserted_id:
            raise HTTPException(status_code=500, detail="Failed to create order")
        
        logger.info(f"Order created successfully: {order_id} for plan: {order_request.plan}")
        
        return OrderResponse(
            orderId=order_id,
            plan=order_request.plan,
            price=plan_info['price'],
            timestamp=order_doc["timestamp"],
            whatsappNumber=order_doc["whatsappNumber"]
        )
        
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error generating order: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/order/{order_id}")
async def get_order(order_id: str):
    """Get order details by ID"""
    try:
        order = orders_collection.find_one({"orderId": order_id})
        
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        
        # Convert MongoDB document to dict and remove _id
        order.pop('_id', None)
        
        return order
        
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error fetching order {order_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.put("/api/order/{order_id}/fulfill")
async def fulfill_order(order_id: str):
    """Mark an order as fulfilled"""
    try:
        result = orders_collection.update_one(
            {"orderId": order_id},
            {
                "$set": {
                    "fulfilled": True,
                    "fulfilledAt": datetime.now()
                }
            }
        )
        
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Order not found")
        
        logger.info(f"Order {order_id} marked as fulfilled")
        
        return {"message": "Order fulfilled successfully", "orderId": order_id}
        
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error fulfilling order {order_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/orders")
async def get_orders(limit: int = 50, fulfilled: Optional[bool] = None, plan: Optional[str] = None):
    """Get list of orders with optional filtering"""
    try:
        query = {}
        if fulfilled is not None:
            query["fulfilled"] = fulfilled
        if plan is not None:
            query["plan"] = plan
        
        orders = list(orders_collection.find(query).sort("timestamp", -1).limit(limit))
        
        # Remove MongoDB _id from results
        for order in orders:
            order.pop('_id', None)
        
        return {"orders": orders, "count": len(orders)}
        
    except Exception as e:
        logger.error(f"Error fetching orders: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/stats")
async def get_stats():
    """Get basic statistics"""
    try:
        total_orders = orders_collection.count_documents({})
        fulfilled_orders = orders_collection.count_documents({"fulfilled": True})
        pending_orders = total_orders - fulfilled_orders
        
        # Count by plan type
        snap_orders = orders_collection.count_documents({"plan": "snap"})
        snappack_orders = orders_collection.count_documents({"plan": "snappack"})
        creator_orders = orders_collection.count_documents({"plan": "creator"})
        
        return {
            "totalOrders": total_orders,
            "fulfilledOrders": fulfilled_orders,
            "pendingOrders": pending_orders,
            "planBreakdown": {
                "snap": snap_orders,
                "snappack": snappack_orders,
                "creator": creator_orders
            }
        }
        
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/plans")
async def get_plans():
    """Get available plans and their details"""
    return {"plans": PLAN_DETAILS}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)