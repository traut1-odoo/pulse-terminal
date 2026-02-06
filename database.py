from sqlalchemy import create_engine, Column, String, Float, Integer, Text, JSON, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os

Base = declarative_base()

class Ticker(Base):
    __tablename__ = 'tickers'
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String(10), unique=True, nullable=False)
    category = Column(String(50), nullable=False)

class Portfolio(Base):
    __tablename__ = 'portfolio'
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String(10), unique=True, nullable=False)
    quantity = Column(Float, default=0)
    avg_price = Column(Float, default=0)

class Transaction(Base):
    """Transaction history for portfolio tracking"""
    __tablename__ = 'transactions'
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String(10), nullable=False)
    transaction_type = Column(String(10), nullable=False)  # 'BUY' or 'SELL'
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    date = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text, default='')

class Alert(Base):
    __tablename__ = 'alerts'
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String(10), unique=True, nullable=False)
    high = Column(Float, nullable=True)
    low = Column(Float, nullable=True)

class Note(Base):
    __tablename__ = 'notes'
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String(10), unique=True, nullable=False)
    content = Column(Text, default='')

class Settings(Base):
    __tablename__ = 'settings'
    
    id = Column(Integer, primary_key=True)
    key = Column(String(50), unique=True, nullable=False)
    value = Column(String(255))

# Database connection
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./watchlist.db')

# Fix for Render.com PostgreSQL URL
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """Initialize database tables"""
    Base.metadata.create_all(bind=engine)
    
    # Add default settings
    db = SessionLocal()
    try:
        theme_setting = db.query(Settings).filter_by(key='theme').first()
        if not theme_setting:
            db.add(Settings(key='theme', value='dark'))
            db.commit()
    except:
        pass
    finally:
        db.close()

def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
