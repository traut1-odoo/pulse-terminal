import yfinance as yf
from fastapi import FastAPI, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session
import pandas as pd
import numpy as np
from datetime import datetime
import io
import csv

from database import init_db, get_db, Ticker, Portfolio, Alert, Note, Settings

app = FastAPI(title="Pulse 4.0 Institutional Terminal")

# CORS configuration for web access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    init_db()
    print("✅ Database initialized")

class PositionModel(BaseModel):
    quantity: float = 0
    avg_price: float = 0

class TickerModel(BaseModel):
    symbol: str
    category: str

class AlertModel(BaseModel):
    high: Optional[float] = None
    low: Optional[float] = None

class NoteModel(BaseModel):
    notes: str

def get_pct_change(series, days):
    if len(series) < days + 1:
        return 0
    try:
        start_val = series.iloc[-(days+1)]
        end_val = series.iloc[-1]
        if start_val == 0 or pd.isna(start_val): 
            return 0
        return round(((end_val - start_val) / start_val) * 100, 2)
    except:
        return 0

def format_earnings_date(earnings_date):
    """Format earnings date to readable string"""
    try:
        if isinstance(earnings_date, (int, float)):
            dt = datetime.fromtimestamp(earnings_date)
        elif isinstance(earnings_date, str):
            dt = datetime.fromisoformat(earnings_date.replace('Z', '+00:00'))
        else:
            dt = earnings_date
        
        now = datetime.now()
        if dt.date() < now.date():
            return f"{dt.strftime('%b %d, %Y')} (Past)"
        elif dt.date() == now.date():
            return "Today"
        else:
            days_until = (dt.date() - now.date()).days
            if days_until == 1:
                return "Tomorrow"
            elif days_until <= 7:
                return f"In {days_until} days ({dt.strftime('%b %d')})"
            else:
                return dt.strftime('%b %d, %Y')
    except:
        return None

def fetch_news_enhanced(symbol):
    """Enhanced news fetching"""
    news_items = []
    try:
        t = yf.Ticker(symbol)
        news_data = t.news
        if news_data and len(news_data) > 0:
            for n in news_data[:8]:
                try:
                    pub_time = "Recent"
                    if 'providerPublishTime' in n:
                        pub_date = datetime.fromtimestamp(n['providerPublishTime'])
                        time_diff = datetime.now() - pub_date
                        if time_diff.days == 0:
                            hours = time_diff.seconds // 3600
                            if hours == 0:
                                mins = time_diff.seconds // 60
                                pub_time = f"{mins}m ago" if mins > 0 else "Just now"
                            else:
                                pub_time = f"{hours}h ago"
                        elif time_diff.days == 1:
                            pub_time = "Yesterday"
                        elif time_diff.days < 7:
                            pub_time = f"{time_diff.days}d ago"
                        else:
                            pub_time = pub_date.strftime("%b %d")
                    
                    thumbnail = ""
                    if 'thumbnail' in n and n['thumbnail']:
                        if isinstance(n['thumbnail'], dict) and 'resolutions' in n['thumbnail']:
                            resolutions = n['thumbnail']['resolutions']
                            if resolutions and len(resolutions) > 0:
                                thumbnail = resolutions[0].get('url', '')
                    
                    news_items.append({
                        "title": n.get('title', 'No Title'),
                        "link": n.get('link', '#'),
                        "publisher": n.get('publisher', 'Yahoo Finance'),
                        "published": pub_time,
                        "thumbnail": thumbnail
                    })
                except Exception as e:
                    print(f"Error parsing news item: {e}")
                    continue
    except Exception as e:
        print(f"Error fetching news for {symbol}: {e}")
    
    if not news_items:
        news_items = [
            {
                "title": f"Latest {symbol} News & Analysis",
                "link": f"https://news.google.com/search?q={symbol}+stock",
                "publisher": "Google News",
                "published": "Live",
                "thumbnail": ""
            },
            {
                "title": f"{symbol} Stock Analysis & Research",
                "link": f"https://www.marketwatch.com/investing/stock/{symbol.lower()}",
                "publisher": "MarketWatch", 
                "published": "Live",
                "thumbnail": ""
            },
            {
                "title": f"{symbol} Financial Statements",
                "link": f"https://finance.yahoo.com/quote/{symbol}/financials",
                "publisher": "Yahoo Finance",
                "published": "Live",
                "thumbnail": ""
            }
        ]
    return news_items

@app.get("/")
async def read_root():
    """Serve the main HTML file"""
    return FileResponse("index.html")

@app.get("/api/screener")
def get_screener(db: Session = Depends(get_db)):
    """Get all stocks with their data"""
    results = []
    
    tickers = db.query(Ticker).all()
    
    for ticker in tickers:
        try:
            symbol = ticker.symbol
            category = ticker.category
            
            t = yf.Ticker(symbol)
            hist = t.history(period="5y")
            
            if hist.empty or len(hist) < 50:
                print(f"Skipping {symbol}: insufficient data")
                continue
                
            close = hist['Close']
            volume = hist['Volume']
            current_price = close.iloc[-1]
            
            info = {}
            try:
                info = t.info or {}
            except:
                pass
            
            # Calculate moving averages
            ma50 = close.rolling(50).mean().iloc[-1]
            ma100 = close.rolling(100).mean().iloc[-1]
            ma250 = close.rolling(250).mean().iloc[-1]
            
            # Calculate RSI
            try:
                delta = close.diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs.iloc[-1]))
                rsi = round(rsi, 2) if not np.isnan(rsi) else '—'
            except:
                rsi = '—'
            
            # Average volume
            avg_volume = volume.tail(20).mean() if len(volume) >= 20 else volume.mean()
            
            # Volatility
            returns = close.pct_change().dropna()
            volatility = returns.std() * np.sqrt(252) * 100
            
            # Portfolio
            pos = db.query(Portfolio).filter_by(symbol=symbol).first()
            if pos:
                quantity = pos.quantity
                avg_price = pos.avg_price
            else:
                quantity = 0
                avg_price = 0
            
            total_value = quantity * current_price
            cost_basis = quantity * avg_price
            pnl = total_value - cost_basis if quantity > 0 else 0
            pnl_pct = round((pnl / cost_basis) * 100, 2) if cost_basis > 0 else 0
            
            # Alerts
            alert = db.query(Alert).filter_by(symbol=symbol).first()
            alert_data = {}
            alert_triggered = False
            if alert:
                if alert.high:
                    alert_data['high'] = alert.high
                    if current_price >= alert.high:
                        alert_triggered = True
                if alert.low:
                    alert_data['low'] = alert.low
                    if current_price <= alert.low:
                        alert_triggered = True
            
            # Earnings date
            earnings_date_display = None
            try:
                if 'earningsDate' in info and info['earningsDate']:
                    earnings_date = info['earningsDate']
                    if isinstance(earnings_date, list) and len(earnings_date) > 0:
                        earnings_date_display = format_earnings_date(earnings_date[0])
                    else:
                        earnings_date_display = format_earnings_date(earnings_date)
            except:
                pass
            
            # Market cap
            market_cap = info.get('marketCap', 0)
            if market_cap >= 1e12:
                market_cap_display = f"${market_cap/1e12:.2f}T"
            elif market_cap >= 1e9:
                market_cap_display = f"${market_cap/1e9:.2f}B"
            elif market_cap >= 1e6:
                market_cap_display = f"${market_cap/1e6:.2f}M"
            else:
                market_cap_display = "—"
            
            # Dividend yield
            dividend_yield = info.get('dividendYield', 0)
            if dividend_yield and dividend_yield > 0:
                dividend_yield_display = round(dividend_yield * 100, 2)
            else:
                dividend_yield_display = 0
            
            # Notes
            note = db.query(Note).filter_by(symbol=symbol).first()
            notes_text = note.content if note else ""
            
            results.append({
                "symbol": symbol,
                "category": category,
                "price": round(current_price, 2),
                "yesterday": round(close.iloc[-2], 2) if len(close) > 1 else round(current_price, 2),
                "perf": {
                    "1d": get_pct_change(close, 1),
                    "1m": get_pct_change(close, 21),
                    "3m": get_pct_change(close, 63),
                    "6m": get_pct_change(close, 126),
                    "1y": get_pct_change(close, 252),
                    "3y": get_pct_change(close, 756) if len(close) >= 756 else get_pct_change(close, len(close)-1)
                },
                "ma": {
                    "50": round(ma50, 2) if not np.isnan(ma50) else "—",
                    "100": round(ma100, 2) if not np.isnan(ma100) else "—",
                    "250": round(ma250, 2) if not np.isnan(ma250) else "—"
                },
                "stats": {
                    "pe": round(info.get('trailingPE', 0), 2) if info.get('trailingPE') else '—',
                    "rsi": rsi,
                    "eps": round(info.get('trailingEps', 0), 2) if info.get('trailingEps') else '—',
                    "beta": round(info.get('beta', 0), 2) if info.get('beta') else '—',
                    "sector": info.get('sector', '—'),
                    "earnings": earnings_date_display,
                    "avg_volume": round(avg_volume, 0) if not np.isnan(avg_volume) else '—',
                    "volatility": round(volatility, 2) if not np.isnan(volatility) else '—',
                    "market_cap": market_cap_display,
                    "52w_high": round(info.get('fiftyTwoWeekHigh', 0), 2) if info.get('fiftyTwoWeekHigh') else '—',
                    "52w_low": round(info.get('fiftyTwoWeekLow', 0), 2) if info.get('fiftyTwoWeekLow') else '—',
                    "dividend_yield": dividend_yield_display
                },
                "sentiment": "Bullish" if current_price > ma250 else "Bearish",
                "position": {
                    "quantity": quantity,
                    "avg_price": avg_price,
                    "current_value": round(total_value, 2),
                    "pnl": round(pnl, 2),
                    "pnl_pct": pnl_pct
                },
                "alerts": alert_data,
                "alert_triggered": alert_triggered,
                "notes": notes_text
            })
            print(f"✓ Processed {symbol}")
        except Exception as e:
            print(f"✗ Error processing {symbol}: {e}")
            continue
    
    return results

@app.get("/api/categories")
def get_categories(db: Session = Depends(get_db)):
    """Get all unique categories"""
    tickers = db.query(Ticker).all()
    categories = list(set([t.category for t in tickers]))
    categories.sort()
    return ["All"] + categories

@app.get("/api/details/{symbol}")
def get_details(symbol: str):
    """Get detailed info for a symbol"""
    try:
        t = yf.Ticker(symbol)
        summary = "No summary available."
        try:
            info = t.info
            summary = info.get('longBusinessSummary', summary) if info else summary
        except:
            pass
        news = fetch_news_enhanced(symbol)
        return {"description": summary, "news": news}
    except Exception as e:
        return {"description": f"Error loading {symbol}", "news": fetch_news_enhanced(symbol)}

@app.post("/api/add")
def add_ticker(data: TickerModel, db: Session = Depends(get_db)):
    """Add a new ticker"""
    symbol_up = data.symbol.upper().strip()
    if not symbol_up:
        return {"status": "error", "message": "Empty symbol"}
    
    existing = db.query(Ticker).filter_by(symbol=symbol_up).first()
    if existing:
        return {"status": "exists"}
    
    new_ticker = Ticker(symbol=symbol_up, category=data.category)
    db.add(new_ticker)
    db.commit()
    
    return {"status": "added"}

@app.delete("/api/ticker/{symbol}")
def delete_ticker(symbol: str, db: Session = Depends(get_db)):
    """Delete a ticker"""
    symbol_up = symbol.upper()
    
    ticker = db.query(Ticker).filter_by(symbol=symbol_up).first()
    if ticker:
        db.delete(ticker)
        
        # Delete related data
        db.query(Portfolio).filter_by(symbol=symbol_up).delete()
        db.query(Alert).filter_by(symbol=symbol_up).delete()
        db.query(Note).filter_by(symbol=symbol_up).delete()
        
        db.commit()
        return {"status": "deleted"}
    
    return {"status": "not_found"}

@app.post("/api/portfolio/{symbol}")
def update_position(symbol: str, position: PositionModel, db: Session = Depends(get_db)):
    """Update portfolio position"""
    symbol_up = symbol.upper()
    
    pos = db.query(Portfolio).filter_by(symbol=symbol_up).first()
    if pos:
        pos.quantity = position.quantity
        pos.avg_price = position.avg_price
    else:
        pos = Portfolio(symbol=symbol_up, quantity=position.quantity, avg_price=position.avg_price)
        db.add(pos)
    
    db.commit()
    return {"status": "saved"}

@app.post("/api/alerts/{symbol}")
def update_alerts(symbol: str, alert_data: AlertModel, db: Session = Depends(get_db)):
    """Update price alerts"""
    symbol_up = symbol.upper()
    
    alert = db.query(Alert).filter_by(symbol=symbol_up).first()
    if alert:
        alert.high = alert_data.high
        alert.low = alert_data.low
    else:
        alert = Alert(symbol=symbol_up, high=alert_data.high, low=alert_data.low)
        db.add(alert)
    
    db.commit()
    return {"status": "saved"}

@app.post("/api/notes/{symbol}")
def update_notes(symbol: str, note_data: NoteModel, db: Session = Depends(get_db)):
    """Update notes"""
    symbol_up = symbol.upper()
    
    note = db.query(Note).filter_by(symbol=symbol_up).first()
    if note:
        note.content = note_data.notes
    else:
        note = Note(symbol=symbol_up, content=note_data.notes)
        db.add(note)
    
    db.commit()
    return {"status": "saved"}

@app.get("/api/theme")
def get_theme(db: Session = Depends(get_db)):
    """Get theme setting"""
    setting = db.query(Settings).filter_by(key='theme').first()
    if setting:
        return {"theme": setting.value}
    return {"theme": "dark"}

@app.post("/api/theme")
def set_theme(theme: str, db: Session = Depends(get_db)):
    """Set theme"""
    setting = db.query(Settings).filter_by(key='theme').first()
    if setting:
        setting.value = theme
    else:
        setting = Settings(key='theme', value=theme)
        db.add(setting)
    
    db.commit()
    return {"theme": theme}

@app.get("/api/export")
def export_watchlist(db: Session = Depends(get_db)):
    """Export all data as CSV"""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Symbol', 'Category', 'Quantity', 'Avg_Price', 'Alert_High', 'Alert_Low', 'Notes'])
    
    tickers = db.query(Ticker).all()
    
    for t in tickers:
        pos = db.query(Portfolio).filter_by(symbol=t.symbol).first()
        alert = db.query(Alert).filter_by(symbol=t.symbol).first()
        note = db.query(Note).filter_by(symbol=t.symbol).first()
        
        writer.writerow([
            t.symbol,
            t.category,
            pos.quantity if pos else 0,
            pos.avg_price if pos else 0,
            alert.high if alert else '',
            alert.low if alert else '',
            note.content if note else ''
        ])
    
    output.seek(0)
    return {"csv": output.getvalue()}

@app.post("/api/import")
async def import_watchlist(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Import data from CSV"""
    contents = await file.read()
    decoded = contents.decode('utf-8')
    reader = csv.DictReader(io.StringIO(decoded))
    
    imported = 0
    for row in reader:
        try:
            symbol = row['Symbol'].upper()
            category = row.get('Category', 'Short Term')
            
            existing = db.query(Ticker).filter_by(symbol=symbol).first()
            if not existing:
                ticker = Ticker(symbol=symbol, category=category)
                db.add(ticker)
                imported += 1
            
            if row.get('Quantity') and row.get('Avg_Price'):
                pos = db.query(Portfolio).filter_by(symbol=symbol).first()
                if pos:
                    pos.quantity = float(row['Quantity'])
                    pos.avg_price = float(row['Avg_Price'])
                else:
                    pos = Portfolio(symbol=symbol, quantity=float(row['Quantity']), avg_price=float(row['Avg_Price']))
                    db.add(pos)
            
            if row.get('Alert_High') or row.get('Alert_Low'):
                alert = db.query(Alert).filter_by(symbol=symbol).first()
                if alert:
                    if row.get('Alert_High'):
                        alert.high = float(row['Alert_High'])
                    if row.get('Alert_Low'):
                        alert.low = float(row['Alert_Low'])
                else:
                    alert = Alert(
                        symbol=symbol,
                        high=float(row['Alert_High']) if row.get('Alert_High') else None,
                        low=float(row['Alert_Low']) if row.get('Alert_Low') else None
                    )
                    db.add(alert)
            
            if row.get('Notes'):
                note = db.query(Note).filter_by(symbol=symbol).first()
                if note:
                    note.content = row['Notes']
                else:
                    note = Note(symbol=symbol, content=row['Notes'])
                    db.add(note)
                    
        except Exception as e:
            print(f"Import error for row {row}: {e}")
            continue
    
    db.commit()
    return {"status": "imported", "count": imported}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
