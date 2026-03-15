from dotenv import load_dotenv
load_dotenv()

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router as api_router

app = FastAPI(
    title="StockSage AI Backend",
    description="Multi-Agent Indian Stock Market Analyzer API",
    version="1.0.0"
)

# --- CORS ---
# For local dev: http://localhost:3000
# For production: set ALLOWED_ORIGINS env var in Railway to your Vercel URL
# e.g. ALLOWED_ORIGINS=https://your-app.vercel.app,https://your-custom-domain.com
_raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(api_router, prefix="/api")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
