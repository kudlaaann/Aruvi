from dotenv import load_dotenv
from pathlib import Path
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

from fastapi import FastAPI, APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse, HTMLResponse
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os, logging, io, csv, json, asyncio, tempfile
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, timezone, timedelta
from bson import ObjectId
import bcrypt, jwt

# Google Drive imports
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI()
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITHM = "HS256"

# ========== AUTH HELPERS ==========

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))

def create_access_token(user_id: str, email: str) -> str:
    payload = {"sub": user_id, "email": email, "exp": datetime.now(timezone.utc) + timedelta(days=30), "type": "access"}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_user(request: Request) -> dict:
    token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return {"id": str(user["_id"]), "email": user["email"], "name": user.get("name", "")}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# ========== MODELS ==========

class LoginRequest(BaseModel):
    email: str
    password: str

class ProjectCreate(BaseModel):
    name: str
    initial_plaster_area: float
    final_plastered_area: float
    bag_usage_history: List[dict] = []
    invoiced_amount: float
    amount_received: float
    status: str = "Pending"

class BagUsageEntry(BaseModel):
    project_id: str
    date: str
    bag_type: str
    quantity: int

class TransactionCreate(BaseModel):
    date: str
    amount: float
    type: str
    mode: str
    linked_project_id: Optional[str] = None
    linked_project_name: Optional[str] = None
    category: Optional[str] = None
    description: str = ""

class PartnerCreate(BaseModel):
    name: str
    total_investment: float = 0

class PartnerTransaction(BaseModel):
    partner_id: str
    amount: float
    type: str
    date: str

class InventoryPurchase(BaseModel):
    bags: int
    bag_type: str
    amount: float
    date: str
    mode: str = "Bank"


# ========== HELPERS ==========

def serialize_doc(doc):
    if doc and "_id" in doc:
        doc["id"] = str(doc["_id"])
        del doc["_id"]
    return doc

async def get_settings():
    settings = await db.settings.find_one()
    if not settings:
        settings = {"bank_balance": 0, "petty_cash_balance": 0}
        await db.settings.insert_one(settings)
    return serialize_doc(settings)

async def update_balance_field(field: str, amount: float):
    await db.settings.update_one({}, {"$inc": {field: amount}}, upsert=True)


# ========== AUTH ENDPOINTS ==========

@api_router.post("/auth/login")
async def login(req: LoginRequest):
    email = req.email.strip().lower()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token(str(user["_id"]), user["email"])
    return {"token": token, "user": {"id": str(user["_id"]), "email": user["email"], "name": user.get("name", "")}}

@api_router.get("/auth/me")
async def get_me(user=Depends(get_current_user)):
    return user


# ========== DASHBOARD ==========

@api_router.get("/dashboard")
async def get_dashboard(user=Depends(get_current_user)):
    try:
        settings = await get_settings()
        bank_bal = settings.get("bank_balance", 0)
        petty_bal = settings.get("petty_cash_balance", 0)
        projects = await db.projects.find().to_list(1000)
        total_receivables = sum(p.get("pending_amount", 0) for p in projects)
        all_transactions = await db.transactions.find().to_list(10000)
        total_income = sum(t["amount"] for t in all_transactions if t.get("type") == "Income")
        total_expenses = sum(t["amount"] for t in all_transactions if t.get("type") == "Expense")
        inv = await db.inventory.find_one() or {}
        np = inv.get("naturoplast_purchased", 0)
        ip = inv.get("iraniya_purchased", 0)
        nu, iu = 0, 0
        for p in projects:
            for e in p.get("bag_usage_history", []):
                if e.get("bag_type") == "Naturoplast": nu += e.get("quantity", 0)
                elif e.get("bag_type") == "Iraniya": iu += e.get("quantity", 0)
        partners = await db.partners.find().to_list(1000)
        total_partner_balance = sum(p.get("current_balance", 0) for p in partners)
        monthly = {}
        for t in all_transactions:
            dt = t.get("date")
            if isinstance(dt, str): key = dt[:7]
            elif isinstance(dt, datetime): key = dt.strftime("%Y-%m")
            else: key = "unknown"
            if key not in monthly: monthly[key] = {"income": 0, "expense": 0}
            if t["type"] == "Income": monthly[key]["income"] += t["amount"]
            else: monthly[key]["expense"] += t["amount"]
        bank_txns = [serialize_doc(dict(t)) for t in all_transactions if t.get("mode") == "Bank"]
        # Check Drive status
        drive_creds = await db.drive_credentials.find_one()
        drive_connected = drive_creds is not None
        last_backup = await db.backup_log.find_one(sort=[("timestamp", -1)])
        return {
            "total_balance": bank_bal + petty_bal, "bank_balance": bank_bal, "petty_cash_balance": petty_bal,
            "total_receivables": total_receivables, "total_income": total_income, "total_expenses": total_expenses,
            "profit_loss": total_income - total_expenses, "total_stock": (np + ip) - (nu + iu),
            "naturoplast_stock": np - nu, "iraniya_stock": ip - iu,
            "naturoplast_purchased": np, "iraniya_purchased": ip, "naturoplast_used": nu, "iraniya_used": iu,
            "total_partner_balance": total_partner_balance, "monthly_breakdown": monthly,
            "bank_transactions": bank_txns,
            "drive_connected": drive_connected,
            "last_backup": serialize_doc(last_backup) if last_backup else None,
        }
    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== PROJECTS ==========

@api_router.get("/projects")
async def get_projects(user=Depends(get_current_user)):
    projects = await db.projects.find().to_list(1000)
    return [serialize_doc(p) for p in projects]

@api_router.get("/projects/{project_id}")
async def get_project_detail(project_id: str, user=Depends(get_current_user)):
    project = await db.projects.find_one({"_id": ObjectId(project_id)})
    if not project: raise HTTPException(status_code=404, detail="Not found")
    project = serialize_doc(project)
    linked_txns = await db.transactions.find({"linked_project_id": project_id}).sort("date", -1).to_list(1000)
    project["linked_transactions"] = [serialize_doc(t) for t in linked_txns]
    return project

@api_router.post("/projects")
async def create_project(project: ProjectCreate, user=Depends(get_current_user)):
    d = project.dict()
    d["bags_used"] = sum(e.get("quantity", 0) for e in d.get("bag_usage_history", []))
    d["pending_amount"] = d["invoiced_amount"] - d["amount_received"]
    d["created_at"] = datetime.now(timezone.utc)
    d["updated_at"] = datetime.now(timezone.utc)
    result = await db.projects.insert_one(d)
    created = await db.projects.find_one({"_id": result.inserted_id})
    return serialize_doc(created)

@api_router.put("/projects/{project_id}")
async def update_project(project_id: str, project: ProjectCreate, user=Depends(get_current_user)):
    d = project.dict()
    d["bags_used"] = sum(e.get("quantity", 0) for e in d.get("bag_usage_history", []))
    d["pending_amount"] = d["invoiced_amount"] - d["amount_received"]
    d["updated_at"] = datetime.now(timezone.utc)
    result = await db.projects.update_one({"_id": ObjectId(project_id)}, {"$set": d})
    if result.matched_count == 0: raise HTTPException(status_code=404, detail="Not found")
    updated = await db.projects.find_one({"_id": ObjectId(project_id)})
    return serialize_doc(updated)

@api_router.post("/projects/{project_id}/bag-usage")
async def add_bag_usage(project_id: str, entry: BagUsageEntry, user=Depends(get_current_user)):
    project = await db.projects.find_one({"_id": ObjectId(project_id)})
    if not project: raise HTTPException(status_code=404, detail="Not found")
    usage = {"date": entry.date, "bag_type": entry.bag_type, "quantity": entry.quantity}
    await db.projects.update_one({"_id": ObjectId(project_id)}, {"$push": {"bag_usage_history": usage}, "$inc": {"bags_used": entry.quantity}})
    updated = await db.projects.find_one({"_id": ObjectId(project_id)})
    return serialize_doc(updated)

@api_router.delete("/projects/{project_id}")
async def delete_project(project_id: str, user=Depends(get_current_user)):
    result = await db.projects.delete_one({"_id": ObjectId(project_id)})
    if result.deleted_count == 0: raise HTTPException(status_code=404, detail="Not found")
    return {"message": "Deleted"}


# ========== TRANSACTIONS ==========

@api_router.get("/transactions")
async def get_transactions(start_date: Optional[str] = None, end_date: Optional[str] = None, mode: Optional[str] = None, user=Depends(get_current_user)):
    query = {}
    if start_date and end_date: query["date"] = {"$gte": start_date, "$lte": end_date}
    if mode: query["mode"] = mode
    txns = await db.transactions.find(query).sort("date", -1).to_list(10000)
    return [serialize_doc(t) for t in txns]

@api_router.post("/transactions")
async def create_transaction(transaction: TransactionCreate, user=Depends(get_current_user)):
    d = transaction.dict()
    d["created_at"] = datetime.now(timezone.utc)
    if d.get("linked_project_id") and not d.get("linked_project_name"):
        proj = await db.projects.find_one({"_id": ObjectId(d["linked_project_id"])})
        if proj: d["linked_project_name"] = proj.get("name", "")
    result = await db.transactions.insert_one(d)
    if d["mode"] == "Bank":
        await update_balance_field("bank_balance", d["amount"] if d["type"] == "Income" else -d["amount"])
    elif d["mode"] == "Petty Cash":
        await update_balance_field("petty_cash_balance", d["amount"] if d["type"] == "Income" else -d["amount"])
    created = await db.transactions.find_one({"_id": result.inserted_id})
    return serialize_doc(created)

@api_router.put("/transactions/{tid}")
async def update_transaction(tid: str, transaction: TransactionCreate, user=Depends(get_current_user)):
    old = await db.transactions.find_one({"_id": ObjectId(tid)})
    if not old: raise HTTPException(status_code=404, detail="Not found")
    if old["mode"] == "Bank": await update_balance_field("bank_balance", -old["amount"] if old["type"] == "Income" else old["amount"])
    elif old["mode"] == "Petty Cash": await update_balance_field("petty_cash_balance", -old["amount"] if old["type"] == "Income" else old["amount"])
    d = transaction.dict()
    if d.get("linked_project_id") and not d.get("linked_project_name"):
        proj = await db.projects.find_one({"_id": ObjectId(d["linked_project_id"])})
        if proj: d["linked_project_name"] = proj.get("name", "")
    await db.transactions.update_one({"_id": ObjectId(tid)}, {"$set": d})
    if d["mode"] == "Bank": await update_balance_field("bank_balance", d["amount"] if d["type"] == "Income" else -d["amount"])
    elif d["mode"] == "Petty Cash": await update_balance_field("petty_cash_balance", d["amount"] if d["type"] == "Income" else -d["amount"])
    updated = await db.transactions.find_one({"_id": ObjectId(tid)})
    return serialize_doc(updated)

@api_router.delete("/transactions/{tid}")
async def delete_transaction(tid: str, user=Depends(get_current_user)):
    txn = await db.transactions.find_one({"_id": ObjectId(tid)})
    if not txn: raise HTTPException(status_code=404, detail="Not found")
    if txn["mode"] == "Bank": await update_balance_field("bank_balance", -txn["amount"] if txn["type"] == "Income" else txn["amount"])
    elif txn["mode"] == "Petty Cash": await update_balance_field("petty_cash_balance", -txn["amount"] if txn["type"] == "Income" else txn["amount"])
    await db.transactions.delete_one({"_id": ObjectId(tid)})
    return {"message": "Deleted"}


# ========== INVENTORY ==========

@api_router.get("/inventory")
async def get_inventory(user=Depends(get_current_user)):
    inv = await db.inventory.find_one()
    if not inv:
        inv = {"naturoplast_purchased": 0, "iraniya_purchased": 0}
        await db.inventory.insert_one(inv)
    projects = await db.projects.find().to_list(1000)
    nu, iu = 0, 0
    for p in projects:
        for e in p.get("bag_usage_history", []):
            if e.get("bag_type") == "Naturoplast": nu += e.get("quantity", 0)
            elif e.get("bag_type") == "Iraniya": iu += e.get("quantity", 0)
    inv = serialize_doc(inv)
    np_val = inv.get("naturoplast_purchased", 0)
    ip_val = inv.get("iraniya_purchased", 0)
    inv.update({"naturoplast_purchased": np_val, "iraniya_purchased": ip_val, "naturoplast_used": nu, "iraniya_used": iu,
                "naturoplast_stock": np_val - nu, "iraniya_stock": ip_val - iu,
                "total_purchased": np_val + ip_val, "total_used": nu + iu, "current_stock": (np_val + ip_val) - (nu + iu)})
    purchases = await db.inventory_purchases.find().sort("date", -1).to_list(1000)
    inv["purchase_history"] = [serialize_doc(p) for p in purchases]
    return inv

@api_router.post("/inventory/purchase")
async def add_inventory_purchase(purchase: InventoryPurchase, user=Depends(get_current_user)):
    field = "naturoplast_purchased" if purchase.bag_type == "Naturoplast" else "iraniya_purchased"
    await db.inventory.update_one({}, {"$inc": {field: purchase.bags}}, upsert=True)
    record = {"bags": purchase.bags, "bag_type": purchase.bag_type, "amount": purchase.amount, "date": purchase.date, "mode": purchase.mode, "created_at": datetime.now(timezone.utc)}
    await db.inventory_purchases.insert_one(record)
    txn = TransactionCreate(date=purchase.date, amount=purchase.amount, type="Expense", mode=purchase.mode, category="Bags", description=f"Purchase of {purchase.bags} {purchase.bag_type} bags")
    await create_transaction(txn, user)
    return {"message": "Purchase added"}


# ========== PARTNERS ==========

@api_router.get("/partners")
async def get_partners(user=Depends(get_current_user)):
    partners = await db.partners.find().to_list(1000)
    result = []
    for p in partners:
        p = serialize_doc(p)
        txn_history = await db.partner_transactions.find({"partner_id": p["id"]}).sort("date", -1).to_list(1000)
        p["transaction_history"] = [serialize_doc(t) for t in txn_history]
        result.append(p)
    return result

@api_router.post("/partners")
async def create_partner(partner: PartnerCreate, user=Depends(get_current_user)):
    d = partner.dict()
    d.update({"total_withdrawals": 0, "current_balance": d["total_investment"], "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)})
    result = await db.partners.insert_one(d)
    created = await db.partners.find_one({"_id": result.inserted_id})
    return serialize_doc(created)

@api_router.put("/partners/{pid}")
async def update_partner(pid: str, partner: PartnerCreate, user=Depends(get_current_user)):
    existing = await db.partners.find_one({"_id": ObjectId(pid)})
    if not existing: raise HTTPException(status_code=404, detail="Not found")
    d = partner.dict()
    d["current_balance"] = d["total_investment"] - existing.get("total_withdrawals", 0)
    d["updated_at"] = datetime.now(timezone.utc)
    await db.partners.update_one({"_id": ObjectId(pid)}, {"$set": d})
    updated = await db.partners.find_one({"_id": ObjectId(pid)})
    return serialize_doc(updated)

@api_router.delete("/partners/{pid}")
async def delete_partner(pid: str, user=Depends(get_current_user)):
    result = await db.partners.delete_one({"_id": ObjectId(pid)})
    if result.deleted_count == 0: raise HTTPException(status_code=404, detail="Not found")
    return {"message": "Deleted"}

@api_router.post("/partners/transaction")
async def partner_transaction(transaction: PartnerTransaction, user=Depends(get_current_user)):
    partner = await db.partners.find_one({"_id": ObjectId(transaction.partner_id)})
    if not partner: raise HTTPException(status_code=404, detail="Not found")
    pname = partner.get("name", "Partner")
    if transaction.type == "Investment":
        await db.partners.update_one({"_id": ObjectId(transaction.partner_id)},
            {"$inc": {"total_investment": transaction.amount, "current_balance": transaction.amount}, "$set": {"updated_at": datetime.now(timezone.utc)}})
        txn = TransactionCreate(date=transaction.date, amount=transaction.amount, type="Income", mode="Bank", description=f"Investment from {pname}")
        await create_transaction(txn, user)
    elif transaction.type == "Withdrawal":
        await db.partners.update_one({"_id": ObjectId(transaction.partner_id)},
            {"$inc": {"total_withdrawals": transaction.amount, "current_balance": -transaction.amount}, "$set": {"updated_at": datetime.now(timezone.utc)}})
        txn = TransactionCreate(date=transaction.date, amount=transaction.amount, type="Expense", mode="Bank", description=f"Withdrawal by {pname}")
        await create_transaction(txn, user)
    record = {"partner_id": transaction.partner_id, "partner_name": pname, "amount": transaction.amount, "type": transaction.type, "date": transaction.date, "created_at": datetime.now(timezone.utc)}
    await db.partner_transactions.insert_one(record)
    return {"message": "Transaction added"}


# ========== EXPORT ==========

@api_router.get("/export/transactions")
async def export_transactions(format: str = "csv", start_date: Optional[str] = None, end_date: Optional[str] = None, user=Depends(get_current_user)):
    query = {}
    if start_date and end_date: query["date"] = {"$gte": start_date, "$lte": end_date}
    txns = await db.transactions.find(query).sort("date", -1).to_list(10000)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["Date", "Type", "Mode", "Category", "Amount", "Description", "Project"])
    writer.writeheader()
    for t in txns:
        dt = t.get("date", "")
        if isinstance(dt, datetime): dt = dt.strftime("%Y-%m-%d")
        writer.writerow({"Date": dt, "Type": t["type"], "Mode": t["mode"], "Category": t.get("category", ""), "Amount": t["amount"], "Description": t.get("description", ""), "Project": t.get("linked_project_name", "")})
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=transactions.csv"})


# ========== GOOGLE DRIVE ==========

def get_drive_flow():
    redirect_uri = os.environ.get("GOOGLE_DRIVE_REDIRECT_URI")
    return Flow.from_client_config(
        {
            "web": {
                "client_id": os.environ["GOOGLE_CLIENT_ID"],
                "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri]
            }
        },
        scopes=["https://www.googleapis.com/auth/drive.file"],
        redirect_uri=redirect_uri,
        autogenerate_code_verifier=False
    )

@api_router.get("/drive/connect")
async def connect_drive(user=Depends(get_current_user)):
    flow = get_drive_flow()
    auth_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent',
        state=user["id"],
        code_challenge_method=None
    )

@api_router.get("/oauth/drive/callback")
async def drive_callback(code: str, state: str = ""):
    try:
        flow = get_drive_flow()
        flow.fetch_token(code=code)
        creds = flow.credentials
        await db.drive_credentials.update_one(
            {"user_id": state},
            {"$set": {"user_id": state, "access_token": creds.token, "refresh_token": creds.refresh_token,
                      "token_uri": creds.token_uri, "client_id": creds.client_id, "client_secret": creds.client_secret,
                      "scopes": list(creds.scopes) if creds.scopes else [], "expiry": creds.expiry.isoformat() if creds.expiry else None,
                      "updated_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True
        )
        frontend_url = os.environ.get("FRONTEND_URL", "")
        return HTMLResponse(f"<html><body><h2>Google Drive Connected!</h2><p>You can close this window and return to the app.</p><script>window.close();</script></body></html>")
    except Exception as e:
        logger.error(f"Drive callback error: {e}")
        return HTMLResponse(f"<html><body><h2>Connection Failed</h2><p>{str(e)}</p></body></html>")

@api_router.get("/drive/status")
async def drive_status(user=Depends(get_current_user)):
    creds = await db.drive_credentials.find_one({"user_id": user["id"]})
    last_backup = await db.backup_log.find_one(sort=[("timestamp", -1)])
    return {"connected": creds is not None, "last_backup": serialize_doc(last_backup) if last_backup else None}

@api_router.post("/drive/backup")
async def trigger_backup(user=Depends(get_current_user)):
    """Manually trigger a backup to Google Drive"""
    try:
        result = await run_drive_backup(user["id"])
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def get_drive_service_for_user(user_id: str):
    creds_doc = await db.drive_credentials.find_one({"user_id": user_id})
    if not creds_doc: return None
    creds = Credentials(token=creds_doc["access_token"], refresh_token=creds_doc.get("refresh_token"),
                        token_uri=creds_doc["token_uri"], client_id=creds_doc["client_id"], client_secret=creds_doc["client_secret"],
                        scopes=creds_doc.get("scopes"))
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())
        await db.drive_credentials.update_one({"user_id": user_id},
            {"$set": {"access_token": creds.token, "expiry": creds.expiry.isoformat() if creds.expiry else None}})
    return build('drive', 'v3', credentials=creds)

async def run_drive_backup(user_id: str):
    service = await get_drive_service_for_user(user_id)
    if not service: raise HTTPException(status_code=400, detail="Google Drive not connected")

    # Find or create backup folder
    folder_name = "Aruvi Housing Solutions - Backup"
    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    folders = results.get('files', [])
    if folders:
        folder_id = folders[0]['id']
    else:
        folder_meta = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'}
        folder = service.files().create(body=folder_meta, fields='id').execute()
        folder_id = folder['id']

    # Create date subfolder
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M")
    subfolder_meta = {'name': date_str, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [folder_id]}
    subfolder = service.files().create(body=subfolder_meta, fields='id').execute()
    subfolder_id = subfolder['id']

    uploaded_files = []

    # Export each collection
    collections = {
        "projects": await db.projects.find().to_list(10000),
        "transactions": await db.transactions.find().to_list(10000),
        "partners": await db.partners.find().to_list(10000),
        "partner_transactions": await db.partner_transactions.find().to_list(10000),
        "inventory_purchases": await db.inventory_purchases.find().to_list(10000),
    }

    # Add settings and inventory
    settings = await db.settings.find_one()
    if settings: collections["settings"] = [settings]
    inv = await db.inventory.find_one()
    if inv: collections["inventory"] = [inv]

    for name, docs in collections.items():
        # Convert ObjectId and datetime to strings
        clean_docs = []
        for doc in docs:
            clean = {}
            for k, v in doc.items():
                if k == "_id": clean["id"] = str(v)
                elif isinstance(v, ObjectId): clean[k] = str(v)
                elif isinstance(v, datetime): clean[k] = v.isoformat()
                else: clean[k] = v
            clean_docs.append(clean)

        # Write JSON file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(clean_docs, f, indent=2, default=str)
            f.flush()
            file_meta = {'name': f'{name}.json', 'parents': [subfolder_id]}
            media = MediaFileUpload(f.name, mimetype='application/json')
            uploaded = service.files().create(body=file_meta, media_body=media, fields='id,name').execute()
            uploaded_files.append(uploaded['name'])

    # Log the backup
    log = {"user_id": user_id, "timestamp": datetime.now(timezone.utc), "folder": date_str, "files": uploaded_files, "status": "success"}
    await db.backup_log.insert_one(log)

    return {"message": f"Backup completed: {len(uploaded_files)} files uploaded", "folder": date_str, "files": uploaded_files}

@api_router.get("/drive/disconnect")
async def disconnect_drive(user=Depends(get_current_user)):
    await db.drive_credentials.delete_many({"user_id": user["id"]})
    return {"message": "Google Drive disconnected"}


# ========== STARTUP ==========

@app.on_event("startup")
async def startup():
    # Seed admin
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@example.com").lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
    existing = await db.users.find_one({"email": admin_email})
    if not existing:
        hashed = hash_password(admin_password)
        await db.users.insert_one({"email": admin_email, "password_hash": hashed, "name": "Aruvi Housing Solutions", "role": "admin", "created_at": datetime.now(timezone.utc)})
        logger.info(f"Admin user created: {admin_email}")
    elif not verify_password(admin_password, existing["password_hash"]):
        await db.users.update_one({"email": admin_email}, {"$set": {"password_hash": hash_password(admin_password)}})
        logger.info("Admin password updated")
    # Create indexes
    await db.users.create_index("email", unique=True)

    # Start auto backup scheduler
    asyncio.create_task(auto_backup_scheduler())

async def auto_backup_scheduler():
    """Run automatic backup every 24 hours"""
    while True:
        await asyncio.sleep(86400)  # 24 hours
        try:
            # Find admin user
            admin = await db.users.find_one({"role": "admin"})
            if admin:
                user_id = str(admin["_id"])
                creds = await db.drive_credentials.find_one({"user_id": user_id})
                if creds:
                    await run_drive_backup(user_id)
                    logger.info("Auto backup completed")
        except Exception as e:
            logger.error(f"Auto backup failed: {e}")


# Include router & middleware
app.include_router(api_router)

app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
