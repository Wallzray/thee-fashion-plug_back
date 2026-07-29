import asyncio
import httpx

# 🛠️ LIVE PRODUCTION CONFIGURATION
PESAPAL_LIVE_BASE = "https://pay.pesapal.com/v3"
LIVE_CONSUMER_KEY = "XruRKZKQeoT2cEuRDBotqXgGef7PvwL8"
LIVE_CONSUMER_SECRET = "suu2SVxDfIQO6m6sfxNbe0BoNYU="

async def fetch_my_ipn_ids():
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    
    # Step 1: Authenticate using the exact flat lowercase formatting
    auth_url = f"{PESAPAL_LIVE_BASE}/api/Auth/RequestToken"
    auth_payload = {
        "consumer_key": LIVE_CONSUMER_KEY,
        "consumer_secret": LIVE_CONSUMER_SECRET
    }
    
    async with httpx.AsyncClient() as client:
        auth_resp = await client.post(auth_url, headers=headers, json=auth_payload)
        token = auth_resp.json().get("token")
        
        if not token:
            print("❌ Auth failed. Verify your main consumer credentials.")
            return
            
        # Step 2: Hit PesaPal's secret list retriever endpoint
        list_url = f"{PESAPAL_LIVE_BASE}/api/URLSetup/GetIpnList"
        headers["Authorization"] = f"Bearer {token}"
        
        list_resp = await client.get(list_url, headers=headers)
        
        print("\n" + "="*70)
        print("📊 LIVE AP1 3.0 REGISTERED ENDPOINTS RETRIEVED:")
        print("="*70)
        
        # Iterating through all records saved under your merchant profile
        for item in list_resp.json():
            print(f"🔗 URL:     {item.get('url')}")
            print(f"🆔 IPN ID:  {item.get('ipn_id')}  <--- COPY THIS ONE")
            print(f"⚡ STATUS:  {item.get('status')}")
            print("-"*70)

if __name__ == "__main__":
    asyncio.run(fetch_my_ipn_ids())