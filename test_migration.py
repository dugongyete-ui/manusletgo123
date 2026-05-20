import asyncio
import os
import sys
from dotenv import load_dotenv

# Tambahkan path backend ke sys.path
sys.path.append('/home/ubuntu/ai-manus/backend')

# Load .env
load_dotenv('/home/ubuntu/ai-manus/backend/.env')

async def test_e2b_sandbox():
    print("--- Mengetes E2B Sandbox ---")
    from app.infrastructure.external.sandbox.e2b_sandbox import E2BSandbox
    
    try:
        print("Mencoba membuat sandbox E2B...")
        sandbox = await E2BSandbox.create()
        print(f"Berhasil membuat sandbox! ID: {sandbox.id}")
        print(f"Hostname: {sandbox.ip}")
        print(f"CDP URL: {sandbox.cdp_url}")
        
        print("Menghancurkan sandbox...")
        await sandbox.destroy()
        print("Sandbox berhasil dihancurkan.")
        return True
    except Exception as e:
        print(f"Gagal mengetes E2B Sandbox: {e}")
        return False

async def test_mongodb():
    print("\n--- Mengetes MongoDB ---")
    from motor.motor_asyncio import AsyncIOMotorClient
    uri = os.getenv("MONGODB_URI")
    db_name = os.getenv("MONGODB_DATABASE")
    
    try:
        client = AsyncIOMotorClient(uri)
        db = client[db_name]
        # Coba ping
        await db.command("ping")
        print(f"Berhasil terhubung ke MongoDB: {db_name}")
        return True
    except Exception as e:
        print(f"Gagal terhubung ke MongoDB: {e}")
        return False

async def test_redis():
    print("\n--- Mengetes Redis ---")
    import redis.asyncio as redis
    host = os.getenv("REDIS_HOST")
    port = int(os.getenv("REDIS_PORT"))
    password = os.getenv("REDIS_PASSWORD")
    
    try:
        r = redis.Redis(host=host, port=port, password=password, decode_responses=True)
        await r.ping()
        print(f"Berhasil terhubung ke Redis: {host}:{port}")
        return True
    except Exception as e:
        print(f"Gagal terhubung ke Redis: {e}")
        return False

async def main():
    e2b_ok = await test_e2b_sandbox()
    mongo_ok = await test_mongodb()
    redis_ok = await test_redis()
    
    print("\n--- Ringkasan Hasil ---")
    print(f"E2B Sandbox: {'OK' if e2b_ok else 'FAILED'}")
    print(f"MongoDB: {'OK' if mongo_ok else 'FAILED'}")
    print(f"Redis: {'OK' if redis_ok else 'FAILED'}")

if __name__ == "__main__":
    asyncio.run(main())
