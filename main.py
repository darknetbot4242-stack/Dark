#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════╗
║     BALİNA AVCISI V6.0 - WHALE EYE PRO                 ║
║     Open Interest + Funding Rate + Spoofing Motorlu     ║
║     Gerçek Balina Takip Sistemi                         ║
║     6 Aylık Emeğin Zirvesi                              ║
╚══════════════════════════════════════════════════════════╝

YENİ MOTORLAR (V6.0):
  - OPEN INTEREST DELTA: Fiyat-OI uyumsuzluğu balina izi
  - FUNDING RATE DEDEKTÖRÜ: Aşırı fonlama ters işlem sinyali
  - ORDERBOOK SPOOFING: Sahte emir duvarı tespiti
  - CVD (Cumulative Volume Delta): Agresif alış/satış dengesi
"""

import signal
import copy
import os
import json
import time
import asyncio
import logging
import hashlib
import hmac
from typing import Any, Dict, List, Optional, Tuple
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlencode

import requests

try:
    import websockets
except Exception:
    websockets = None
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# =========================================================
# VERSİYON
# =========================================================
VERSION_NAME = "Balina Avcısı V6.1 WHALE EYE PRO WS + SR + HATA HAFIZASI + HELAL FİLTRE - 100 COIN + 15M MA GUARD V2"

# =========================================================
# ENV / AYARLAR
# =========================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# Binance API (YENI - OI ve Funding için)
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "").strip()
BINANCE_FAPI_BASE = os.getenv("BINANCE_FAPI_BASE", "https://fapi.binance.com").strip().rstrip("/")
BINANCE_DAPI_BASE = os.getenv("BINANCE_DAPI_BASE", "https://dapi.binance.com").strip().rstrip("/")
BINANCE_SPOT_BASE = os.getenv("BINANCE_SPOT_BASE", "https://api.binance.com").strip().rstrip("/")

OKX_BASE_URL = os.getenv("OKX_BASE_URL", "https://www.okx.com").strip().rstrip("/")
OKX_INST_TYPE = os.getenv("OKX_INST_TYPE", "SWAP").strip().upper()

BINANCE_CONFIRM_ENABLED = os.getenv("BINANCE_CONFIRM_ENABLED", "true").lower() == "true"
BINANCE_CONFIRM_REQUIRED = os.getenv("BINANCE_CONFIRM_REQUIRED", "false").lower() == "true"
BINANCE_CONFIRM_BASE_URL = os.getenv("BINANCE_CONFIRM_BASE_URL", "https://data-api.binance.vision").strip().rstrip("/")
BINANCE_CONFIRM_SCORE_PASS = float(os.getenv("BINANCE_CONFIRM_SCORE_PASS", "13"))
BINANCE_CONFIRM_SCORE_SOFT = float(os.getenv("BINANCE_CONFIRM_SCORE_SOFT", "8"))
BINANCE_CONFIRM_FAIL_OPEN_SCORE = float(os.getenv("BINANCE_CONFIRM_FAIL_OPEN_SCORE", "78"))
MAX_BINANCE_OKX_PRICE_GAP_PCT = float(os.getenv("MAX_BINANCE_OKX_PRICE_GAP_PCT", "0.35"))
HARD_BINANCE_OKX_PRICE_GAP_PCT = float(os.getenv("HARD_BINANCE_OKX_PRICE_GAP_PCT", "0.75"))

MEMORY_FILE = os.getenv("MEMORY_FILE", "balina_avcisi_v6_memory.json").strip()
LOG_FILE = os.getenv("LOG_FILE", "balina_avcisi_v6.log").strip()
TIMEZONE_NAME = os.getenv("TIMEZONE_NAME", "Europe/Istanbul").strip()

AUTO_START_MESSAGE = os.getenv("AUTO_START_MESSAGE", "false").lower() == "true"
AUTO_HEARTBEAT = os.getenv("AUTO_HEARTBEAT", "false").lower() == "true"
HEARTBEAT_INTERVAL_SEC = int(float(os.getenv("HEARTBEAT_INTERVAL_SEC", "7200")))
HOT_SCAN_INTERVAL_SEC = float(os.getenv("HOT_SCAN_INTERVAL_SEC", "1.5"))
DEEP_SCAN_INTERVAL_SEC = float(os.getenv("DEEP_SCAN_INTERVAL_SEC", "2"))
MEMORY_SAVE_INTERVAL_SEC = int(float(os.getenv("MEMORY_SAVE_INTERVAL_SEC", "60")))
FOLLOWUP_CHECK_INTERVAL_SEC = int(float(os.getenv("FOLLOWUP_CHECK_INTERVAL_SEC", "300")))
FOLLOWUP_DELAY_SEC = int(float(os.getenv("FOLLOWUP_DELAY_SEC", "7200")))
HOT_TTL_SEC = int(float(os.getenv("HOT_TTL_SEC", "1800")))
ALERT_COOLDOWN_MIN = int(float(os.getenv("ALERT_COOLDOWN_MIN", "180")))
SETUP_COOLDOWN_MIN = int(float(os.getenv("SETUP_COOLDOWN_MIN", "120")))
MAX_HOT_CANDIDATES = int(float(os.getenv("MAX_HOT_CANDIDATES", "28")))
MAX_DEEP_ANALYSIS_PER_CYCLE = int(float(os.getenv("MAX_DEEP_ANALYSIS_PER_CYCLE", "35")))

MIN_CANDIDATE_SCORE = float(os.getenv("MIN_CANDIDATE_SCORE", "27"))
MIN_READY_SCORE = float(os.getenv("MIN_READY_SCORE", "44"))
MIN_SIGNAL_SCORE = float(os.getenv("MIN_SIGNAL_SCORE", "62"))
MIN_VERIFY_SCORE_FOR_SIGNAL = float(os.getenv("MIN_VERIFY_SCORE_FOR_SIGNAL", "22"))
MIN_QUALITY_SCORE = float(os.getenv("MIN_QUALITY_SCORE", "4.5"))
DAILY_SHORT_TOTAL_LIMIT = int(float(os.getenv("DAILY_SHORT_TOTAL_LIMIT", "7")))
MAX_SIGNAL_PER_SCAN = int(float(os.getenv("MAX_SIGNAL_PER_SCAN", "1")))
SIGNAL_SPACING_SEC = int(float(os.getenv("SIGNAL_SPACING_SEC", "0")))
# SIGNAL_SPACING_SEC=0 olsa bile hot/deep döngüleri aynı anda sinyal basmasın diye iç koruma.
INTERNAL_SIGNAL_SPACING_SEC = float(os.getenv("INTERNAL_SIGNAL_SPACING_SEC", "2.0"))

# =========================================================
# YENI MOTOR AYARLARI - V6 WHALE EYE
# =========================================================

# --- OPEN INTEREST MOTORU ---
OI_ENGINE_ENABLED = os.getenv("OI_ENGINE_ENABLED", "true").lower() == "true"
OI_SHORT_MIN_DIVERGENCE_SCORE = float(os.getenv("OI_SHORT_MIN_DIVERGENCE_SCORE", "6.0"))
OI_LONG_MIN_DIVERGENCE_SCORE = float(os.getenv("OI_LONG_MIN_DIVERGENCE_SCORE", "6.0"))
OI_DELTA_LOOKBACK_MIN = int(float(os.getenv("OI_DELTA_LOOKBACK_MIN", "15")))
OI_CACHE_SEC = int(float(os.getenv("OI_CACHE_SEC", "30")))
OI_MIN_CHANGE_PCT = float(os.getenv("OI_MIN_CHANGE_PCT", "0.45"))
OI_BEARISH_PRICE_DROP_PCT = float(os.getenv("OI_BEARISH_PRICE_DROP_PCT", "0.30"))
OI_BULLISH_PRICE_RISE_PCT = float(os.getenv("OI_BULLISH_PRICE_RISE_PCT", "0.30"))

# --- FUNDING RATE MOTORU ---
FUNDING_ENGINE_ENABLED = os.getenv("FUNDING_ENGINE_ENABLED", "true").lower() == "true"
FUNDING_SHORT_THRESHOLD = float(os.getenv("FUNDING_SHORT_THRESHOLD", "0.0500"))
FUNDING_LONG_THRESHOLD = float(os.getenv("FUNDING_LONG_THRESHOLD", "-0.0300"))
FUNDING_CACHE_SEC = int(float(os.getenv("FUNDING_CACHE_SEC", "60")))
FUNDING_SHORT_BONUS = float(os.getenv("FUNDING_SHORT_BONUS", "8.0"))
FUNDING_LONG_BONUS = float(os.getenv("FUNDING_LONG_BONUS", "8.0"))
FUNDING_EXTREME_SHORT_BONUS = float(os.getenv("FUNDING_EXTREME_SHORT_BONUS", "14.0"))
FUNDING_EXTREME_LONG_BONUS = float(os.getenv("FUNDING_EXTREME_LONG_BONUS", "14.0"))
FUNDING_EXTREME_THRESHOLD = float(os.getenv("FUNDING_EXTREME_THRESHOLD", "0.1000"))

# --- ORDERBOOK SPOOFING MOTORU ---
SPOOFING_ENGINE_ENABLED = os.getenv("SPOOFING_ENGINE_ENABLED", "true").lower() == "true"
SPOOFING_CACHE_SEC = float(os.getenv("SPOOFING_CACHE_SEC", "1.5"))
SPOOFING_MIN_WALL_SIZE_MULT = float(os.getenv("SPOOFING_MIN_WALL_SIZE_MULT", "3.0"))
SPOOFING_WALL_VANISH_SEC = float(os.getenv("SPOOFING_WALL_VANISH_SEC", "3.0"))
SPOOFING_SHORT_SCORE_BONUS = float(os.getenv("SPOOFING_SHORT_SCORE_BONUS", "5.0"))
SPOOFING_LONG_SCORE_BONUS = float(os.getenv("SPOOFING_LONG_SCORE_BONUS", "5.0"))

# --- CVD (Cumulative Volume Delta) MOTORU ---
CVD_ENGINE_ENABLED = os.getenv("CVD_ENGINE_ENABLED", "true").lower() == "true"
CVD_CACHE_SEC = int(float(os.getenv("CVD_CACHE_SEC", "15")))
CVD_LOOKBACK_MIN = int(float(os.getenv("CVD_LOOKBACK_MIN", "30")))
CVD_SHORT_DIVERGENCE_SCORE = float(os.getenv("CVD_SHORT_DIVERGENCE_SCORE", "3.0"))
CVD_LONG_DIVERGENCE_SCORE = float(os.getenv("CVD_LONG_DIVERGENCE_SCORE", "3.0"))

ONE_ACTIVE_TRADE_MODE = os.getenv("ONE_ACTIVE_TRADE_MODE", "false").lower() == "true"
ACTIVE_TRADE_BLOCK_SEC = int(float(os.getenv("ACTIVE_TRADE_BLOCK_SEC", "0")))
SCORE_OVERRIDE_GAP = float(os.getenv("SCORE_OVERRIDE_GAP", "12"))
PRICE_OVERRIDE_MOVE_PCT = float(os.getenv("PRICE_OVERRIDE_MOVE_PCT", "0.90"))
TREND_GUARD_ENABLED = os.getenv("TREND_GUARD_ENABLED", "true").lower() == "true"
TREND_GUARD_MIN_PUMP_10M = float(os.getenv("TREND_GUARD_MIN_PUMP_10M", "0.90"))
TREND_GUARD_MIN_PUMP_20M = float(os.getenv("TREND_GUARD_MIN_PUMP_20M", "1.35"))
TREND_GUARD_MIN_RSI_1M = float(os.getenv("TREND_GUARD_MIN_RSI_1M", "58"))
TREND_GUARD_MIN_RSI_5M = float(os.getenv("TREND_GUARD_MIN_RSI_5M", "57"))
TREND_GUARD_SCORE_BLOCK = float(os.getenv("TREND_GUARD_SCORE_BLOCK", "5"))
TREND_BREAKDOWN_MIN_SCORE = float(os.getenv("TREND_BREAKDOWN_MIN_SCORE", "7.2"))
TREND_WATCH_TTL_SEC = int(float(os.getenv("TREND_WATCH_TTL_SEC", "3600")))
MIN_RED_CANDLES_FOR_SHORT = int(float(os.getenv("MIN_RED_CANDLES_FOR_SHORT", "2")))

SHORT_STOP_ATR_MULT = float(os.getenv("SHORT_STOP_ATR_MULT", "2.20"))
SHORT_STOP_WICK_ATR_BUFFER = float(os.getenv("SHORT_STOP_WICK_ATR_BUFFER", "0.55"))
SHORT_MIN_STOP_PCT = float(os.getenv("SHORT_MIN_STOP_PCT", "0.55"))
SHORT_MAX_STOP_PCT = float(os.getenv("SHORT_MAX_STOP_PCT", "3.10"))
SHORT_TP1_R_MULT = float(os.getenv("SHORT_TP1_R_MULT", "1.20"))
SHORT_TP2_R_MULT = float(os.getenv("SHORT_TP2_R_MULT", "1.75"))
SHORT_TP3_R_MULT = float(os.getenv("SHORT_TP3_R_MULT", "2.55"))
MIN_RR_TP1 = float(os.getenv("MIN_RR_TP1", "1.05"))

BREAKDOWN_ASSIST_ENABLED = os.getenv("BREAKDOWN_ASSIST_ENABLED", "true").lower() == "true"
BREAKDOWN_ASSIST_MIN_SCORE = float(os.getenv("BREAKDOWN_ASSIST_MIN_SCORE", "6.6"))
BREAKDOWN_ASSIST_STRONG_SCORE = float(os.getenv("BREAKDOWN_ASSIST_STRONG_SCORE", "8.6"))
BREAKDOWN_ASSIST_CANDIDATE_FLOOR = float(os.getenv("BREAKDOWN_ASSIST_CANDIDATE_FLOOR", "28"))
BREAKDOWN_ASSIST_READY_FLOOR = float(os.getenv("BREAKDOWN_ASSIST_READY_FLOOR", "48"))
BREAKDOWN_ASSIST_VERIFY_BONUS = float(os.getenv("BREAKDOWN_ASSIST_VERIFY_BONUS", "3"))
BREAKDOWN_ASSIST_STRONG_VERIFY_BONUS = float(os.getenv("BREAKDOWN_ASSIST_STRONG_VERIFY_BONUS", "5"))

GORUNMEYEN_YUZ_ENABLED = os.getenv("GORUNMEYEN_YUZ_ENABLED", "true").lower() == "true"
GORUNMEYEN_YUZ_REQUIRE_FOR_SIGNAL = os.getenv("GORUNMEYEN_YUZ_REQUIRE_FOR_SIGNAL", "true").lower() == "true"
GORUNMEYEN_YUZ_ALLOW_RISKY_SCALP = os.getenv("GORUNMEYEN_YUZ_ALLOW_RISKY_SCALP", "true").lower() == "true"
GORUNMEYEN_YUZ_MIN_CLEAN_SCORE = float(os.getenv("GORUNMEYEN_YUZ_MIN_CLEAN_SCORE", "72"))
GORUNMEYEN_YUZ_MIN_SCALP_SCORE = float(os.getenv("GORUNMEYEN_YUZ_MIN_SCALP_SCORE", "58"))
GORUNMEYEN_YUZ_MIN_WATCH_SCORE = float(os.getenv("GORUNMEYEN_YUZ_MIN_WATCH_SCORE", "43"))
GORUNMEYEN_YUZ_MIN_DROP_FROM_PEAK = float(os.getenv("GORUNMEYEN_YUZ_MIN_DROP_FROM_PEAK", "0.08"))
GORUNMEYEN_YUZ_MAX_DROP_FROM_PEAK = float(os.getenv("GORUNMEYEN_YUZ_MAX_DROP_FROM_PEAK", "1.15"))
GORUNMEYEN_YUZ_TOO_LATE_DROP = float(os.getenv("GORUNMEYEN_YUZ_TOO_LATE_DROP", "1.45"))
GORUNMEYEN_YUZ_MIN_RR_TP1 = float(os.getenv("GORUNMEYEN_YUZ_MIN_RR_TP1", "0.80"))
GORUNMEYEN_YUZ_ORDERBOOK_ENABLED = os.getenv("GORUNMEYEN_YUZ_ORDERBOOK_ENABLED", "true").lower() == "true"
GORUNMEYEN_YUZ_TRADES_ENABLED = os.getenv("GORUNMEYEN_YUZ_TRADES_ENABLED", "true").lower() == "true"
GORUNMEYEN_YUZ_FLOW_PREFILTER_SCORE = float(os.getenv("GORUNMEYEN_YUZ_FLOW_PREFILTER_SCORE", "35"))
GORUNMEYEN_YUZ_BINANCE_FAIL_OVERRIDE = os.getenv("GORUNMEYEN_YUZ_BINANCE_FAIL_OVERRIDE", "true").lower() == "true"
GORUNMEYEN_YUZ_BOOK_CACHE_SEC = float(os.getenv("GORUNMEYEN_YUZ_BOOK_CACHE_SEC", "2.0"))
GORUNMEYEN_YUZ_TRADE_CACHE_SEC = float(os.getenv("GORUNMEYEN_YUZ_TRADE_CACHE_SEC", "2.0"))

TEPE_ERKEN_MOD_ENABLED = os.getenv("TEPE_ERKEN_MOD_ENABLED", "true").lower() == "true"
TEPE_ERKEN_MIN_PUMP_20M = float(os.getenv("TEPE_ERKEN_MIN_PUMP_20M", "0.85"))
TEPE_ERKEN_MIN_PUMP_1H = float(os.getenv("TEPE_ERKEN_MIN_PUMP_1H", "1.20"))
TEPE_ERKEN_MIN_DROP_FROM_PEAK = float(os.getenv("TEPE_ERKEN_MIN_DROP_FROM_PEAK", "0.03"))
TEPE_ERKEN_MAX_DROP_FROM_PEAK = float(os.getenv("TEPE_ERKEN_MAX_DROP_FROM_PEAK", "1.05"))
TEPE_ERKEN_TOO_LATE_DROP = float(os.getenv("TEPE_ERKEN_TOO_LATE_DROP", "1.45"))
TEPE_ERKEN_MAX_PEAK_AGE_CANDLES = int(float(os.getenv("TEPE_ERKEN_MAX_PEAK_AGE_CANDLES", "14")))
TEPE_ERKEN_MIN_EXIT_SCORE = float(os.getenv("TEPE_ERKEN_MIN_EXIT_SCORE", "4.0"))
TEPE_ERKEN_BLOCK_LOCAL_LOW_BOUNCE = float(os.getenv("TEPE_ERKEN_BLOCK_LOCAL_LOW_BOUNCE", "0.25"))

RISKY_SCALP_CLOSE_TP_ENABLED = os.getenv("RISKY_SCALP_CLOSE_TP_ENABLED", "true").lower() == "true"
RISKY_SCALP_TP1_PCT = float(os.getenv("RISKY_SCALP_TP1_PCT", "0.45"))
RISKY_SCALP_TP2_PCT = float(os.getenv("RISKY_SCALP_TP2_PCT", "0.65"))
RISKY_SCALP_TP3_PCT = float(os.getenv("RISKY_SCALP_TP3_PCT", "0.90"))
RISKY_SCALP_MIN_RR_TP1 = float(os.getenv("RISKY_SCALP_MIN_RR_TP1", "0.35"))

CLOSE_CONFIRM_GATE_ENABLED = os.getenv("CLOSE_CONFIRM_GATE_ENABLED", "true").lower() == "true"
CLOSE_CONFIRM_REQUIRE_5M = os.getenv("CLOSE_CONFIRM_REQUIRE_5M", "true").lower() == "true"
CLOSE_CONFIRM_REQUIRE_15M = os.getenv("CLOSE_CONFIRM_REQUIRE_15M", "true").lower() == "true"
CLOSE_CONFIRM_MIN_5M_SCORE = float(os.getenv("CLOSE_CONFIRM_MIN_5M_SCORE", "4.2"))
CLOSE_CONFIRM_MIN_15M_SCORE = float(os.getenv("CLOSE_CONFIRM_MIN_15M_SCORE", "2.6"))
CLOSE_CONFIRM_CLEAN_5M_SCORE = float(os.getenv("CLOSE_CONFIRM_CLEAN_5M_SCORE", "6.1"))
CLOSE_CONFIRM_CLEAN_15M_SCORE = float(os.getenv("CLOSE_CONFIRM_CLEAN_15M_SCORE", "4.0"))

ICT_ENGINE_ENABLED = os.getenv("ICT_ENGINE_ENABLED", "true").lower() == "true"
LONG_ENGINE_ENABLED = os.getenv("LONG_ENGINE_ENABLED", "true").lower() == "true"
SHORT_ICT_CONTEXT_ENABLED = os.getenv("SHORT_ICT_CONTEXT_ENABLED", "true").lower() == "true"

ICT_SWING_LOOKBACK_5M = int(float(os.getenv("ICT_SWING_LOOKBACK_5M", "72")))
ICT_LIQUIDITY_LOOKBACK_1M = int(float(os.getenv("ICT_LIQUIDITY_LOOKBACK_1M", "24")))
ICT_DISCOUNT_FIB_LOW = float(os.getenv("ICT_DISCOUNT_FIB_LOW", "0.50"))
ICT_DISCOUNT_FIB_HIGH = float(os.getenv("ICT_DISCOUNT_FIB_HIGH", "0.618"))
ICT_PREMIUM_FIB_LOW = float(os.getenv("ICT_PREMIUM_FIB_LOW", "0.382"))
ICT_PREMIUM_FIB_HIGH = float(os.getenv("ICT_PREMIUM_FIB_HIGH", "0.50"))
ICT_ZONE_TOLERANCE_PCT = float(os.getenv("ICT_ZONE_TOLERANCE_PCT", "0.18"))
ICT_MIN_RANGE_PCT = float(os.getenv("ICT_MIN_RANGE_PCT", "1.10"))
ICT_MIN_SWEEP_PCT = float(os.getenv("ICT_MIN_SWEEP_PCT", "0.03"))
ICT_MIN_CHOCH_SCORE = float(os.getenv("ICT_MIN_CHOCH_SCORE", "5.0"))
ICT_MIN_FVG_BODY_ATR = float(os.getenv("ICT_MIN_FVG_BODY_ATR", "0.75"))

ICT_PRO_MODE_ENABLED = os.getenv("ICT_PRO_MODE_ENABLED", "true").lower() == "true"
ICT_PIVOT_LEFT = int(float(os.getenv("ICT_PIVOT_LEFT", "2")))
ICT_PIVOT_RIGHT = int(float(os.getenv("ICT_PIVOT_RIGHT", "2")))
ICT_EQUAL_LEVEL_TOLERANCE_PCT = float(os.getenv("ICT_EQUAL_LEVEL_TOLERANCE_PCT", "0.08"))
ICT_ORDER_BLOCK_LOOKBACK = int(float(os.getenv("ICT_ORDER_BLOCK_LOOKBACK", "28")))
ICT_FVG_LOOKBACK = int(float(os.getenv("ICT_FVG_LOOKBACK", "36")))
ICT_MIN_DISPLACEMENT_ATR = float(os.getenv("ICT_MIN_DISPLACEMENT_ATR", "1.05"))
ICT_MAX_OB_DISTANCE_PCT = float(os.getenv("ICT_MAX_OB_DISTANCE_PCT", "1.10"))
ICT_MAX_FVG_DISTANCE_PCT = float(os.getenv("ICT_MAX_FVG_DISTANCE_PCT", "1.20"))
ICT_SHORT_MIN_PRO_SCORE = float(os.getenv("ICT_SHORT_MIN_PRO_SCORE", "8.0"))
ICT_LONG_MIN_PRO_SCORE = float(os.getenv("ICT_LONG_MIN_PRO_SCORE", "8.0"))
ICT_REQUIRE_PRO_CONTEXT_FOR_SIGNAL = os.getenv("ICT_REQUIRE_PRO_CONTEXT_FOR_SIGNAL", "false").lower() == "true"
ICT_KILLZONE_ENABLED = os.getenv("ICT_KILLZONE_ENABLED", "true").lower() == "true"
ICT_LONDON_KILLZONE_START = int(float(os.getenv("ICT_LONDON_KILLZONE_START", "10")))
ICT_LONDON_KILLZONE_END = int(float(os.getenv("ICT_LONDON_KILLZONE_END", "13")))
ICT_NY_KILLZONE_START = int(float(os.getenv("ICT_NY_KILLZONE_START", "15")))
ICT_NY_KILLZONE_END = int(float(os.getenv("ICT_NY_KILLZONE_END", "19")))

LONG_DAILY_TOTAL_LIMIT = int(float(os.getenv("LONG_DAILY_TOTAL_LIMIT", "7")))
LONG_MIN_CANDIDATE_SCORE = float(os.getenv("LONG_MIN_CANDIDATE_SCORE", "24"))
LONG_MIN_READY_SCORE = float(os.getenv("LONG_MIN_READY_SCORE", "30"))
LONG_MIN_SIGNAL_SCORE = float(os.getenv("LONG_MIN_SIGNAL_SCORE", "74"))
LONG_MIN_VERIFY_SCORE = float(os.getenv("LONG_MIN_VERIFY_SCORE", "22"))
LONG_MIN_QUALITY_SCORE = float(os.getenv("LONG_MIN_QUALITY_SCORE", "6.0"))
LONG_MIN_DROP_20M = float(os.getenv("LONG_MIN_DROP_20M", "0.55"))
LONG_MIN_DROP_1H = float(os.getenv("LONG_MIN_DROP_1H", "1.10"))
LONG_MAX_BOUNCE_FROM_LOW_PCT = float(os.getenv("LONG_MAX_BOUNCE_FROM_LOW_PCT", "1.35"))
LONG_MIN_BUY_TO_SELL = float(os.getenv("LONG_MIN_BUY_TO_SELL", "1.18"))
LONG_MIN_5M_CONFIRM_SCORE = float(os.getenv("LONG_MIN_5M_CONFIRM_SCORE", "3.0"))
LONG_MIN_15M_CONFIRM_SCORE = float(os.getenv("LONG_MIN_15M_CONFIRM_SCORE", "0.5"))
LONG_REQUIRE_5M_CONFIRM = os.getenv("LONG_REQUIRE_5M_CONFIRM", "true").lower() == "true"
LONG_REQUIRE_15M_CONFIRM = os.getenv("LONG_REQUIRE_15M_CONFIRM", "false").lower() == "true"
LONG_STOP_ATR_MULT = float(os.getenv("LONG_STOP_ATR_MULT", "2.10"))
LONG_STOP_WICK_ATR_BUFFER = float(os.getenv("LONG_STOP_WICK_ATR_BUFFER", "0.55"))
LONG_MIN_STOP_PCT = float(os.getenv("LONG_MIN_STOP_PCT", "0.55"))
LONG_MAX_STOP_PCT = float(os.getenv("LONG_MAX_STOP_PCT", "3.10"))
LONG_TP1_R_MULT = float(os.getenv("LONG_TP1_R_MULT", "1.15"))
LONG_TP2_R_MULT = float(os.getenv("LONG_TP2_R_MULT", "1.75"))
LONG_TP3_R_MULT = float(os.getenv("LONG_TP3_R_MULT", "2.50"))
LONG_MIN_RR_TP1 = float(os.getenv("LONG_MIN_RR_TP1", "1.05"))

# ALGO örneği düzeltmesi: BEARISH yapı + satıcı akışı + zayıf hacim varken
# ICT discount/FVG/OB tek başına LONG AL üretemez.
LONG_BEARISH_CONTEXT_HARD_BLOCK_ENABLED = os.getenv("LONG_BEARISH_CONTEXT_HARD_BLOCK_ENABLED", "true").lower() == "true"
LONG_SELL_TO_BUY_HARD_BLOCK = float(os.getenv("LONG_SELL_TO_BUY_HARD_BLOCK", "1.20"))
LONG_WEAK_VOL_1M_BLOCK = float(os.getenv("LONG_WEAK_VOL_1M_BLOCK", "0.40"))
LONG_WEAK_VOL_5M_BLOCK = float(os.getenv("LONG_WEAK_VOL_5M_BLOCK", "0.25"))
LONG_REQUIRE_TRUE_STRUCTURE_UP = os.getenv("LONG_REQUIRE_TRUE_STRUCTURE_UP", "true").lower() == "true"

FIXED_TP1_PCT = float(os.getenv("FIXED_TP1_PCT", "1.0"))
FIXED_TP2_PCT = float(os.getenv("FIXED_TP2_PCT", "1.5"))
FIXED_TP3_PCT = float(os.getenv("FIXED_TP3_PCT", "2.0"))
SHORT_STRUCTURE_EXTRA_BUFFER_PCT = float(os.getenv("SHORT_STRUCTURE_EXTRA_BUFFER_PCT", "0.18"))
LONG_STRUCTURE_EXTRA_BUFFER_PCT = float(os.getenv("LONG_STRUCTURE_EXTRA_BUFFER_PCT", "0.18"))

# =========================================================
# PROFESYONEL AI OTOMATİK SİNYAL KÖPRÜSÜ
# =========================================================
# Ana bot SIGNAL üretmese bile AI yön/zeka motoru belirli aralıklarla coinleri tarar.
# AI gerçekten LONG_AL/SHORT_AL üretirse dışarıya sadece normal AL mesajı gider.
PRO_AI_AUTOSIGNAL_LOOP_ENABLED = os.getenv("PRO_AI_AUTOSIGNAL_LOOP_ENABLED", "true").lower() == "true"
PRO_AI_AUTOSIGNAL_INTERVAL_SEC = float(os.getenv("PRO_AI_AUTOSIGNAL_INTERVAL_SEC", "18"))
PRO_AI_AUTOSIGNAL_BATCH_SIZE = int(float(os.getenv("PRO_AI_AUTOSIGNAL_BATCH_SIZE", "2")))
PRO_AI_AUTOSIGNAL_INCLUDE_EXTERNAL = os.getenv("PRO_AI_AUTOSIGNAL_INCLUDE_EXTERNAL", "true").lower() == "true"
PRO_AI_AUTOSIGNAL_PER_SYMBOL_COOLDOWN_SEC = int(float(os.getenv("PRO_AI_AUTOSIGNAL_PER_SYMBOL_COOLDOWN_SEC", "900")))
PRO_AI_AUTOSIGNAL_MAX_SEND_PER_CYCLE = int(float(os.getenv("PRO_AI_AUTOSIGNAL_MAX_SEND_PER_CYCLE", "1")))
# AI otomatik köprü için sert tekrar kilidi. Aynı coin + aynı yön yeniden basılmaz.
# Varsayılan 6 saat: kullanıcı daha önce aynı coin tekrarını bug olarak gördüğü için.
PRO_AI_AUTOSIGNAL_SAME_DIRECTION_COOLDOWN_SEC = int(float(os.getenv("PRO_AI_AUTOSIGNAL_SAME_DIRECTION_COOLDOWN_SEC", "21600")))
# Telegram API cevap vermese bile mesaj gitmiş olabilir; bu yüzden AI sinyalinde gönderimden ÖNCE kilit atılır.
PRO_AI_AUTOSIGNAL_PRELOCK_ENABLED = os.getenv("PRO_AI_AUTOSIGNAL_PRELOCK_ENABLED", "true").lower() == "true"

# =========================================================
# AI OTOMATİK SİNYAL FINAL KAPI — GERÇEK GÖNDERİM FİLTRESİ
# =========================================================
# Bu ayarlar artık sadece yazıda kalmaz; LONG/SHORT AL gönderilmeden hemen önce okunur.
PRO_AI_AUTOSIGNAL_MIN_CONFIDENCE = float(os.getenv("PRO_AI_AUTOSIGNAL_MIN_CONFIDENCE", "70"))
PRO_AI_AUTOSIGNAL_MIN_SIGNAL_SCORE = float(os.getenv("PRO_AI_AUTOSIGNAL_MIN_SIGNAL_SCORE", "62"))
PRO_AI_AUTOSIGNAL_MAX_RISK = float(os.getenv("PRO_AI_AUTOSIGNAL_MAX_RISK", "35"))
PRO_AI_AUTOSIGNAL_LONG_MIN_EDGE = float(os.getenv("PRO_AI_AUTOSIGNAL_LONG_MIN_EDGE", "45"))
PRO_AI_AUTOSIGNAL_SHORT_MIN_EDGE = float(os.getenv("PRO_AI_AUTOSIGNAL_SHORT_MIN_EDGE", "40"))
PRO_AI_AUTOSIGNAL_MIN_RR = float(os.getenv("PRO_AI_AUTOSIGNAL_MIN_RR", "1.05"))

# SHORT için geç kalmış düşüş filtresi:
# Bot tepede/ilk kırılımda short arasın; düşüş bittikten sonra short basmasın.
PRO_AI_AUTOSIGNAL_SHORT_LATE_FILTER_ENABLED = os.getenv("PRO_AI_AUTOSIGNAL_SHORT_LATE_FILTER_ENABLED", "true").lower() in ("1", "true", "yes", "on")
PRO_AI_AUTOSIGNAL_SHORT_RSI1_OVERSOLD_BLOCK = float(os.getenv("PRO_AI_AUTOSIGNAL_SHORT_RSI1_OVERSOLD_BLOCK", "35"))
PRO_AI_AUTOSIGNAL_SHORT_RSI5_WEAK_BLOCK = float(os.getenv("PRO_AI_AUTOSIGNAL_SHORT_RSI5_WEAK_BLOCK", "42"))
PRO_AI_AUTOSIGNAL_SHORT_RSI15_WEAK_BLOCK = float(os.getenv("PRO_AI_AUTOSIGNAL_SHORT_RSI15_WEAK_BLOCK", "45"))
PRO_AI_AUTOSIGNAL_SHORT_MIN_TOP_CONTEXT = os.getenv("PRO_AI_AUTOSIGNAL_SHORT_MIN_TOP_CONTEXT", "true").lower() in ("1", "true", "yes", "on")
PRO_AI_AUTOSIGNAL_SHORT_MIN_PUMP_CONTEXT = float(os.getenv("PRO_AI_AUTOSIGNAL_SHORT_MIN_PUMP_CONTEXT", "0.80"))
PRO_AI_AUTOSIGNAL_SHORT_MAX_NEAR_PEAK_PCT = float(os.getenv("PRO_AI_AUTOSIGNAL_SHORT_MAX_NEAR_PEAK_PCT", "1.40"))

# LONG için ters taraftaki aşırı ısınma filtresi.
PRO_AI_AUTOSIGNAL_LONG_OVERHEAT_FILTER_ENABLED = os.getenv("PRO_AI_AUTOSIGNAL_LONG_OVERHEAT_FILTER_ENABLED", "true").lower() in ("1", "true", "yes", "on")
PRO_AI_AUTOSIGNAL_LONG_RSI1_OVERHEAT_BLOCK = float(os.getenv("PRO_AI_AUTOSIGNAL_LONG_RSI1_OVERHEAT_BLOCK", "74"))
PRO_AI_AUTOSIGNAL_LONG_RSI5_OVERHEAT_BLOCK = float(os.getenv("PRO_AI_AUTOSIGNAL_LONG_RSI5_OVERHEAT_BLOCK", "72"))

# ONE STOP FIX / SHORT SON GÜVENLİK KAPISI
# SHORT için ters CVD + Binance FAIL + zayıf pump + düşük RSI kombinasyonunu dış sinyalden keser.
SHORT_CONTEXT_GUARD_ENABLED = os.getenv("SHORT_CONTEXT_GUARD_ENABLED", "true").lower() in ("1", "true", "yes", "on")
SHORT_BLOCK_ON_BULLISH_CVD_AND_BINANCE_FAIL = os.getenv("SHORT_BLOCK_ON_BULLISH_CVD_AND_BINANCE_FAIL", "true").lower() in ("1", "true", "yes", "on")
SHORT_CONTEXT_WEAK_PUMP_20M = float(os.getenv("SHORT_CONTEXT_WEAK_PUMP_20M", "0.60"))
SHORT_CONTEXT_WEAK_PUMP_1H = float(os.getenv("SHORT_CONTEXT_WEAK_PUMP_1H", "0.80"))
SHORT_CONTEXT_LATE_RSI1 = float(os.getenv("SHORT_CONTEXT_LATE_RSI1", "42"))
SHORT_CONTEXT_BLOCK_BINANCE_FAIL_WEAK_PUMP_LOW_RSI = os.getenv("SHORT_CONTEXT_BLOCK_BINANCE_FAIL_WEAK_PUMP_LOW_RSI", "true").lower() in ("1", "true", "yes", "on")
SHORT_CONTEXT_BLOCK_BULLISH_CVD_WEAK_PUMP_LOW_RSI = os.getenv("SHORT_CONTEXT_BLOCK_BULLISH_CVD_WEAK_PUMP_LOW_RSI", "true").lower() in ("1", "true", "yes", "on")

# 15M MA GATE — Kullanıcının istediği net kural:
# 15m sarı MA7, pembe MA25 altına inmeden SHORT AL dışarı basılmaz.
SHORT_15M_MA_GATE_ENABLED = os.getenv("SHORT_15M_MA_GATE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
SHORT_15M_FAST_MA = int(float(os.getenv("SHORT_15M_FAST_MA", "7")))
SHORT_15M_SLOW_MA = int(float(os.getenv("SHORT_15M_SLOW_MA", "25")))

# =========================================================
# V6.1 PRO EKLERİ — WS / SR / HAFIZA / REJİM / BACKTEST
# =========================================================
# DeepSeek/harici AI eklemez. Mevcut V6 AI otomatik köprü korunur; yeni katmanlar onu daha profesyonel denetler.

# --- WebSocket canlı orderbook + trade akışı ---
PRO_WS_ENABLED = os.getenv("PRO_WS_ENABLED", "true").lower() in ("1", "true", "yes", "on")
PRO_WS_URL = os.getenv("PRO_WS_URL", "wss://ws.okx.com:8443/ws/v5/public").strip()
PRO_WS_BOOK_CHANNEL = os.getenv("PRO_WS_BOOK_CHANNEL", "books5").strip()
PRO_WS_TRADE_CHANNEL = os.getenv("PRO_WS_TRADE_CHANNEL", "trades").strip()
PRO_WS_SYMBOL_LIMIT = int(float(os.getenv("PRO_WS_SYMBOL_LIMIT", "100")))
PRO_WS_STALE_SEC = float(os.getenv("PRO_WS_STALE_SEC", "8.0"))
PRO_WS_RECONNECT_SEC = float(os.getenv("PRO_WS_RECONNECT_SEC", "3.0"))
PRO_WS_TRADE_HISTORY = int(float(os.getenv("PRO_WS_TRADE_HISTORY", "240")))
PRO_WS_BOOK_HISTORY = int(float(os.getenv("PRO_WS_BOOK_HISTORY", "80")))
PRO_WS_SPOOF_MIN_DROP_RATIO = float(os.getenv("PRO_WS_SPOOF_MIN_DROP_RATIO", "0.42"))
PRO_WS_SPOOF_MIN_GROWTH_RATIO = float(os.getenv("PRO_WS_SPOOF_MIN_GROWTH_RATIO", "2.60"))
PRO_WS_SPOOF_WINDOW_SEC = float(os.getenv("PRO_WS_SPOOF_WINDOW_SEC", "4.0"))

# --- Profesyonel final kapılar ---
PRO_FINAL_GATES_ENABLED = os.getenv("PRO_FINAL_GATES_ENABLED", "true").lower() in ("1", "true", "yes", "on")
SR_FILTER_ENABLED = os.getenv("SR_FILTER_ENABLED", "true").lower() in ("1", "true", "yes", "on")
SR_HARD_BLOCK_ENABLED = os.getenv("SR_HARD_BLOCK_ENABLED", "true").lower() in ("1", "true", "yes", "on")
SR_CLUSTER_TOLERANCE_PCT = float(os.getenv("SR_CLUSTER_TOLERANCE_PCT", "0.18"))
SR_MIN_TOUCHES = int(float(os.getenv("SR_MIN_TOUCHES", "2")))
SR_TP1_WALL_BUFFER_PCT = float(os.getenv("SR_TP1_WALL_BUFFER_PCT", "0.18"))
REGIME_FILTER_ENABLED = os.getenv("REGIME_FILTER_ENABLED", "true").lower() in ("1", "true", "yes", "on")
MACRO_FILTER_ENABLED = os.getenv("MACRO_FILTER_ENABLED", "true").lower() in ("1", "true", "yes", "on")
MACRO_BTC_STRONG_MOVE_PCT = float(os.getenv("MACRO_BTC_STRONG_MOVE_PCT", "0.55"))
MACRO_ETH_STRONG_MOVE_PCT = float(os.getenv("MACRO_ETH_STRONG_MOVE_PCT", "0.70"))
PRO_GATE_BLOCK_ONLY_WEAK_WHALE = os.getenv("PRO_GATE_BLOCK_ONLY_WEAK_WHALE", "true").lower() in ("1", "true", "yes", "on")
PRO_GATE_WHALE_OVERRIDE_SCORE = float(os.getenv("PRO_GATE_WHALE_OVERRIDE_SCORE", "6.0"))

# --- Hata hafızası ---
MISTAKE_MEMORY_ENABLED = os.getenv("MISTAKE_MEMORY_ENABLED", "true").lower() in ("1", "true", "yes", "on")
MISTAKE_MEMORY_MIN_STOPS = int(float(os.getenv("MISTAKE_MEMORY_MIN_STOPS", "1")))
MISTAKE_MEMORY_BLOCK_HOURS = float(os.getenv("MISTAKE_MEMORY_BLOCK_HOURS", "18"))
MISTAKE_MEMORY_KEEP_DAYS = int(float(os.getenv("MISTAKE_MEMORY_KEEP_DAYS", "14")))
MISTAKE_MEMORY_SOFT_BLOCK_SCORE_ADD = float(os.getenv("MISTAKE_MEMORY_SOFT_BLOCK_SCORE_ADD", "14"))

# --- Helal filtre: mevcut meme/çöp bloklarına ek olarak faiz/yield ağırlıklı protokoller isteğe bağlı engellenir ---
HELAL_FILTER_ENABLED = os.getenv("HELAL_FILTER_ENABLED", "true").lower() in ("1", "true", "yes", "on")
HELAL_EXTRA_BLOCKED_COINS = tuple(
    x.strip().upper()
    for x in os.getenv("HELAL_EXTRA_BLOCKED_COINS", "AAVE,COMP,LDO,PENDLE").split(",")
    if x.strip()
)

# --- Backtest / maliyet modeli ---
BACKTEST_DEFAULT_BARS = int(float(os.getenv("BACKTEST_DEFAULT_BARS", "240")))
BACKTEST_FEE_PCT = float(os.getenv("BACKTEST_FEE_PCT", "0.08"))          # giriş+çıkış toplam taker tahmini
BACKTEST_SLIPPAGE_PCT = float(os.getenv("BACKTEST_SLIPPAGE_PCT", "0.04"))
BACKTEST_FUNDING_PCT_PER_8H = float(os.getenv("BACKTEST_FUNDING_PCT_PER_8H", "0.01"))

# --- Pozisyon yönetimi / takip raporu ---
POSITION_MANAGEMENT_ENABLED = os.getenv("POSITION_MANAGEMENT_ENABLED", "true").lower() in ("1", "true", "yes", "on")
TRAILING_AFTER_TP1_ENABLED = os.getenv("TRAILING_AFTER_TP1_ENABLED", "true").lower() in ("1", "true", "yes", "on")
TRAILING_LOCK_PCT_AFTER_TP1 = float(os.getenv("TRAILING_LOCK_PCT_AFTER_TP1", "0.20"))


BLOCKED_COIN_BASE_KEYWORDS = tuple(
    x.strip().upper()
    for x in os.getenv(
        "BLOCKED_COIN_BASE_KEYWORDS",
        "PEPE,1000PEPE,DOGE,SHIB,FLOKI,BONK,WIF,MEME,TURBO,MEW,BRETT,NOT,"
        "BOME,TRUMP,FARTCOIN,PNUT,GOAT,MELANIA,AI16Z,VINE,GRIFFAIN,PIPPIN"
    ).split(",")
    if x.strip()
)

MIN_24H_QUOTE_VOLUME = float(os.getenv("MIN_24H_QUOTE_VOLUME", "1200000"))
KLINE_CACHE_SEC = int(float(os.getenv("KLINE_CACHE_SEC", "12")))
TICKER_CACHE_SEC = int(float(os.getenv("TICKER_CACHE_SEC", "8")))
HTTP_TIMEOUT = int(float(os.getenv("HTTP_TIMEOUT", "12")))
OKX_INSTRUMENT_CACHE_SEC = int(float(os.getenv("OKX_INSTRUMENT_CACHE_SEC", "1800")))
AUTO_SYMBOL_REFRESH_SEC = int(float(os.getenv("AUTO_SYMBOL_REFRESH_SEC", "1800")))
SYMBOL_FAIL_BLOCK_SEC = int(float(os.getenv("SYMBOL_FAIL_BLOCK_SEC", "900")))
SYMBOL_FAIL_FORGET_SEC = int(float(os.getenv("SYMBOL_FAIL_FORGET_SEC", "43200")))
SYMBOL_FAIL_MAX_STREAK = int(float(os.getenv("SYMBOL_FAIL_MAX_STREAK", "2")))

DEFAULT_COINS = [
    "BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", "XRP-USDT-SWAP",
    "BNB-USDT-SWAP", "ADA-USDT-SWAP", "AVAX-USDT-SWAP", "LINK-USDT-SWAP",
    "DOT-USDT-SWAP", "TRX-USDT-SWAP", "LTC-USDT-SWAP", "BCH-USDT-SWAP",
    "UNI-USDT-SWAP", "NEAR-USDT-SWAP", "APT-USDT-SWAP", "ARB-USDT-SWAP",
    "OP-USDT-SWAP", "FIL-USDT-SWAP", "INJ-USDT-SWAP", "TAO-USDT-SWAP",
    "RENDER-USDT-SWAP", "WLD-USDT-SWAP", "TIA-USDT-SWAP", "SEI-USDT-SWAP",
    "PYTH-USDT-SWAP", "ENA-USDT-SWAP", "STX-USDT-SWAP", "STRK-USDT-SWAP",
    "ARKM-USDT-SWAP", "FLOW-USDT-SWAP", "CFX-USDT-SWAP", "MASK-USDT-SWAP",
    "RAY-USDT-SWAP", "AR-USDT-SWAP", "DYDX-USDT-SWAP", "ZRX-USDT-SWAP",
    "IOTA-USDT-SWAP", "ALGO-USDT-SWAP", "HBAR-USDT-SWAP", "XLM-USDT-SWAP",
    "VET-USDT-SWAP", "CHZ-USDT-SWAP", "GALA-USDT-SWAP", "ZIL-USDT-SWAP",
    "SAND-USDT-SWAP", "MANA-USDT-SWAP", "ROSE-USDT-SWAP", "SKL-USDT-SWAP",
    "ANKR-USDT-SWAP", "CELR-USDT-SWAP", "IOST-USDT-SWAP", "ONE-USDT-SWAP",
    "SXP-USDT-SWAP", "CTSI-USDT-SWAP", "RSR-USDT-SWAP", "BLUR-USDT-SWAP",
    "ACH-USDT-SWAP", "API3-USDT-SWAP", "GMT-USDT-SWAP", "LRC-USDT-SWAP",
    "KAVA-USDT-SWAP", "MINA-USDT-SWAP", "WOO-USDT-SWAP", "BAND-USDT-SWAP",
    "STORJ-USDT-SWAP", "ID-USDT-SWAP", "ARPA-USDT-SWAP", "ONT-USDT-SWAP",
    "QTUM-USDT-SWAP", "BAT-USDT-SWAP", "ENJ-USDT-SWAP", "RVN-USDT-SWAP",
    "KNC-USDT-SWAP", "CRV-USDT-SWAP", "JUP-USDT-SWAP", "OM-USDT-SWAP",
    "POLYX-USDT-SWAP", "DUSK-USDT-SWAP", "HOOK-USDT-SWAP", "PHB-USDT-SWAP",
    "MAGIC-USDT-SWAP", "AEVO-USDT-SWAP", "ALT-USDT-SWAP", "ZK-USDT-SWAP",
    "ZRO-USDT-SWAP", "JTO-USDT-SWAP", "JOE-USDT-SWAP", "RDNT-USDT-SWAP",
    "SUSHI-USDT-SWAP", "SNX-USDT-SWAP", "1INCH-USDT-SWAP", "GMX-USDT-SWAP",
    "LPT-USDT-SWAP", "EGLD-USDT-SWAP", "AXS-USDT-SWAP", "THETA-USDT-SWAP",
    "APE-USDT-SWAP", "IMX-USDT-SWAP", "SSV-USDT-SWAP", "ATOM-USDT-SWAP",
]
def coin_base_from_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper().replace("/", "-")
    if s.endswith("-SWAP"):
        s = s[:-5]
    if "-" in s:
        return s.split("-")[0]
    if s.endswith("USDT"):
        return s[:-4]
    return s


def is_blocked_coin_symbol(symbol: str) -> bool:
    base = coin_base_from_symbol(symbol)
    if any(key and key in base for key in BLOCKED_COIN_BASE_KEYWORDS):
        return True
    if HELAL_FILTER_ENABLED and any(key and key in base for key in HELAL_EXTRA_BLOCKED_COINS):
        return True
    return False


def filter_coin_universe(symbols: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for raw in symbols:
        sym = (raw or "").strip().upper()
        if not sym or is_blocked_coin_symbol(sym):
            continue
        if sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    return out


COINS = filter_coin_universe([x.strip().upper() for x in os.getenv("COINS", ",".join(DEFAULT_COINS)).split(",") if x.strip()])

# =========================================================
# LOGGING
# =========================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("balina_avcisi_v6")

# =========================================================
# GLOBAL STATE
# =========================================================
TZ = ZoneInfo(TIMEZONE_NAME)

import threading as _threading
_thread_local = _threading.local()

def _get_session() -> requests.Session:
    if not hasattr(_thread_local, "session"):
        s = requests.Session()
        s.headers.update({"User-Agent": "BalinaAvcisiV6WhaleEye/1.0"})
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=6,
            pool_maxsize=12,
            max_retries=0,
        )
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        _thread_local.session = s
    return _thread_local.session

kline_cache: Dict[str, Tuple[float, List[List[Any]]]] = {}
ticker_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
orderbook_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
trades_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
orderbook_memory: Dict[str, Dict[str, Any]] = {}
instrument_cache: Dict[str, Tuple[float, Dict[str, Dict[str, Any]]]] = {}
okx_live_symbols: Dict[str, Dict[str, Any]] = {}
symbol_fail_state: Dict[str, Dict[str, Any]] = {}

# V6 YENI: OI / Funding / CVD cache'leri
oi_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
funding_cache: Dict[str, Tuple[float, float]] = {}
cvd_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
spoofing_memory: Dict[str, Dict[str, Any]] = {}

# V6.1 PRO WS canlı veri hafızası
ws_orderbooks: Dict[str, Dict[str, Any]] = {}
ws_book_history: Dict[str, deque] = {}
ws_trades: Dict[str, deque] = {}
ws_runtime_state: Dict[str, Any] = {
    "enabled": PRO_WS_ENABLED,
    "connected": False,
    "last_msg_ts": 0.0,
    "last_error": "-",
    "reconnects": 0,
    "subscriptions": 0,
}

memory: Dict[str, Any] = {
    "hot": {},
    "trend_watch": {},
    "signals": {},
    "follows": {},
    "stats": {},
    "daily_short_sent": {},
    "daily_long_sent": {},
    "ai_auto_sent_lock": {},
    "last_signal_ts": 0.0,
    "last_signal_attempt_ts": 0.0,
    "last_diag_ts": 0.0,
    "ai_auto_scan": {},
    "mistake_memory": {},
}

stats: Dict[str, Any] = {
    "analyzed": 0,
    "no_data": 0,
    "api_fail": 0,
    "telegram_fail": 0,
    "hot_add": 0,
    "hot_promote": 0,
    "signal_sent": 0,
    "followup_sent": 0,
    "rejected": 0,
    "cooldown_reject": 0,
    "cooldown_override": 0,
    "trend_strong_reject": 0,
    "trend_guard_block_signal": 0,
    "trend_guard_watch": 0,
    "trend_breakdown_pass": 0,
    "breakdown_candidate_assist": 0,
    "volume_reject": 0,
    "weak_candidate_reject": 0,
    "weak_ready_reject": 0,
    "weak_signal_reject": 0,
    "binance_confirm_pass": 0,
    "binance_confirm_soft": 0,
    "binance_confirm_fail": 0,
    "binance_confirm_unavailable": 0,
    "signal_downgraded_by_binance": 0,
    "daily_short_block": 0,
    "daily_total_block": 0,
    "quality_gate_block": 0,
    "rr_block": 0,
    "invisible_face_clean": 0,
    "invisible_face_scalp": 0,
    "invisible_face_watch": 0,
    "invisible_face_block": 0,
    "invisible_face_promote": 0,
    "invisible_face_downgrade": 0,
    "tepe_early_signal": 0,
    "tepe_late_block": 0,
    "orderbook_ok": 0,
    "orderbook_fail": 0,
    "trades_ok": 0,
    "trades_fail": 0,
    "scan_signal_suppressed": 0,
    "global_gap_block": 0,
    "active_trade_block": 0,
    "invalid_symbol_skip": 0,
    "blocked_symbol_skip": 0,
    "okx_symbol_pruned": 0,
    "okx_symbol_refresh": 0,
    "okx_symbol_fail_block": 0,
    "blocked_coin_skip": 0,
    "close_confirm_block": 0,
    "close_confirm_risky": 0,
    "long_signal_sent": 0,
    "long_candidate": 0,
    "long_ready": 0,
    "long_reject": 0,
    "long_ict_signal": 0,
    "long_quality_block": 0,
    "long_close_confirm_block": 0,
    "long_conflict_block": 0,
    # V6 YENI
    "oi_short_diverge": 0,
    "oi_long_diverge": 0,
    "funding_short_bonus": 0,
    "funding_long_bonus": 0,
    "spoofing_detected": 0,
    "cvd_diverge_short": 0,
    "cvd_diverge_long": 0,
    "whale_eye_block": 0,
    "whale_eye_pass": 0,
    "ai_auto_final_pass": 0,
    "ai_auto_final_block": 0,
    "ai_auto_late_short_block": 0,
    "ai_auto_late_long_block": 0,
    "ws_book_updates": 0,
    "ws_trade_updates": 0,
    "ws_spoofing_detected": 0,
    "sr_block": 0,
    "regime_block": 0,
    "macro_block": 0,
    "mistake_memory_learn": 0,
    "mistake_memory_block": 0,
    "backtest_runs": 0,
    "backtest_cost_applied": 0,
    "position_management_updates": 0,
    "natural_language_hit": 0,
    "short_context_guard_block": 0,
    "short_15m_ma_gate_block": 0,
}

app = None
deep_pointer = 0
ai_pointer = 0


# =========================================================
# GENEL YARDIMCILAR
# =========================================================
def tr_now() -> datetime:
    return datetime.now(TZ)


def tr_str(ts: Optional[float] = None) -> str:
    dt = datetime.fromtimestamp(ts, TZ) if ts else tr_now()
    return dt.strftime("%d.%m.%Y %H:%M:%S")


def tr_day_key(ts: Optional[float] = None) -> str:
    dt = datetime.fromtimestamp(ts, TZ) if ts else tr_now()
    return dt.strftime("%Y-%m-%d")


def clamp(x: float, low: float, high: float) -> float:
    return max(low, min(high, x))


def safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def pct_change(a: float, b: float) -> float:
    if a == 0:
        return 0.0
    return ((b - a) / a) * 100.0


def avg(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def fmt_num(v: float) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "0.0000"
    if abs(v) >= 1000:
        int_part = int(v)
        frac = abs(v - int_part)
        int_str = f"{int_part:,}".replace(",", ".")
        if frac > 1e-12:
            frac_str = f"{frac:.4f}"[1:].replace(".", ",")
            return f"{int_str}{frac_str}"
        return int_str
    if abs(v) >= 1:
        return f"{v:.4f}"
    if abs(v) >= 0.0001:
        return f"{v:.6f}"
    return f"{v:.8f}"


def ensure_memory_shape() -> None:
    global memory
    if not isinstance(memory, dict):
        memory = {}
    memory.setdefault("hot", {})
    memory.setdefault("trend_watch", {})
    memory.setdefault("signals", {})
    memory.setdefault("follows", {})
    memory.setdefault("stats", {})
    memory.setdefault("daily_short_sent", {})
    memory.setdefault("daily_long_sent", {})
    memory.setdefault("ai_auto_sent_lock", {})
    memory.setdefault("last_signal_ts", 0.0)
    memory.setdefault("last_signal_attempt_ts", 0.0)
    memory.setdefault("last_diag_ts", 0.0)
    memory.setdefault("ai_auto_scan", {})
    memory.setdefault("mistake_memory", {})


def load_memory() -> None:
    global memory
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                memory = json.load(f)
            ensure_memory_shape()
            logger.info("Memory yüklendi: %s", MEMORY_FILE)
        except Exception as e:
            logger.exception("Memory yüklenemedi: %s", e)
            memory = {
                "hot": {}, "trend_watch": {}, "signals": {}, "follows": {}, "stats": {}, "daily_short_sent": {}, "daily_long_sent": {},
                "last_signal_ts": 0.0, "last_diag_ts": 0.0
            }
    else:
        ensure_memory_shape()


def save_memory() -> None:
    try:
        ensure_memory_shape()
        def clean_for_json(obj):
            import datetime as dt
            if isinstance(obj, dict):
                return {k: clean_for_json(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [clean_for_json(v) for v in obj]
            elif isinstance(obj, (dt.datetime, dt.date)):
                return obj.isoformat()
            elif isinstance(obj, set):
                return list(obj)
            elif hasattr(obj, '__dict__'):
                return str(obj)
            return obj
        clean_memory = clean_for_json(memory)
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(clean_memory, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("Memory kaydedilemedi: %s", e)


def cleanup_symbol_fail_state() -> None:
    now_ts = time.time()
    for sym in list(symbol_fail_state.keys()):
        rec = symbol_fail_state.get(sym, {})
        last_ts = safe_float(rec.get("last_ts", 0))
        block_until = safe_float(rec.get("block_until", 0))
        if block_until and now_ts >= block_until:
            rec["block_until"] = 0.0
            rec["streak"] = 0
        if last_ts and now_ts - last_ts > SYMBOL_FAIL_FORGET_SEC:
            symbol_fail_state.pop(sym, None)


def cleanup_memory() -> None:
    now_ts = time.time()
    hot = memory.get("hot", {})
    for sym in list(hot.keys()):
        if is_blocked_coin_symbol(sym):
            hot.pop(sym, None)
            continue
        last_seen = safe_float(hot[sym].get("last_seen", 0))
        if now_ts - last_seen > HOT_TTL_SEC:
            hot.pop(sym, None)
    trend_watch = memory.get("trend_watch", {})
    for sym in list(trend_watch.keys()):
        if is_blocked_coin_symbol(sym):
            trend_watch.pop(sym, None)
            continue
        last_seen = safe_float(trend_watch[sym].get("last_seen", 0))
        if now_ts - last_seen > TREND_WATCH_TTL_SEC:
            trend_watch.pop(sym, None)
    follows = memory.get("follows", {})
    for key in list(follows.keys()):
        created = safe_float(follows[key].get("created_ts", 0))
        if now_ts - created > 3 * 24 * 3600:
            follows.pop(key, None)
    daily_short_sent = memory.get("daily_short_sent", {})
    today_key = tr_day_key()
    for day_key in list(daily_short_sent.keys()):
        if day_key != today_key:
            try:
                day_dt = datetime.strptime(day_key, "%Y-%m-%d").replace(tzinfo=TZ)
                if now_ts - day_dt.timestamp() > 7 * 24 * 3600:
                    daily_short_sent.pop(day_key, None)
            except Exception:
                daily_short_sent.pop(day_key, None)
    daily_long_sent = memory.get("daily_long_sent", {})
    for day_key in list(daily_long_sent.keys()):
        if day_key != today_key:
            try:
                day_dt = datetime.strptime(day_key, "%Y-%m-%d").replace(tzinfo=TZ)
                if now_ts - day_dt.timestamp() > 7 * 24 * 3600:
                    daily_long_sent.pop(day_key, None)
            except Exception:
                daily_long_sent.pop(day_key, None)
    # AI otomatik sinyal tekrar kilitlerini temizle
    ai_locks = memory.get("ai_auto_sent_lock", {})
    for lock_key in list(ai_locks.keys()):
        rec = ai_locks.get(lock_key, {}) if isinstance(ai_locks.get(lock_key, {}), dict) else {}
        ts = safe_float(rec.get("ts", 0))
        if not ts or now_ts - ts > max(PRO_AI_AUTOSIGNAL_SAME_DIRECTION_COOLDOWN_SEC, 24 * 3600):
            ai_locks.pop(lock_key, None)
    cleanup_symbol_fail_state()


def note_symbol_fail(symbol: str, reason: str = "") -> None:
    now_ts = time.time()
    rec = symbol_fail_state.setdefault(symbol, {"streak": 0, "last_ts": 0.0, "block_until": 0.0, "last_reason": ""})
    rec["streak"] = int(safe_float(rec.get("streak", 0))) + 1
    rec["last_ts"] = now_ts
    rec["last_reason"] = str(reason)[:220]
    if rec["streak"] >= max(1, SYMBOL_FAIL_MAX_STREAK):
        already_blocked = safe_float(rec.get("block_until", 0)) > now_ts
        rec["block_until"] = now_ts + SYMBOL_FAIL_BLOCK_SEC
        if not already_blocked:
            stats["okx_symbol_fail_block"] += 1
            logger.warning("Coin geçici bloklandı %s | sebep=%s", symbol, rec["last_reason"])


def note_symbol_success(symbol: str) -> None:
    rec = symbol_fail_state.get(symbol)
    if not rec:
        return
    rec["streak"] = 0
    rec["block_until"] = 0.0
    rec["last_reason"] = ""


def symbol_temporarily_blocked(symbol: str) -> bool:
    rec = symbol_fail_state.get(symbol, {})
    return time.time() < safe_float(rec.get("block_until", 0))


def get_blocked_symbol_count() -> int:
    now_ts = time.time()
    return sum(1 for rec in symbol_fail_state.values() if now_ts < safe_float(rec.get("block_until", 0)))


# =========================================================
# BINANCE FUTURES API (YENI - V6 WHALE EYE)
# =========================================================
def _binance_fapi_sign(params: Dict[str, Any]) -> str:
    query = urlencode(params)
    return hmac.new(
        BINANCE_SECRET_KEY.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def _binance_fapi_get(path: str, params: Optional[Dict[str, Any]] = None, signed: bool = False) -> Any:
    url = f"{BINANCE_FAPI_BASE}{path}"
    session = _get_session()
    headers = {}
    if signed and BINANCE_API_KEY:
        headers["X-MBX-APIKEY"] = BINANCE_API_KEY
        if params is None:
            params = {}
        params["timestamp"] = int(time.time() * 1000)
        params["signature"] = _binance_fapi_sign(params)
    resp = session.get(url, params=params or {}, headers=headers, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


async def get_open_interest(symbol: str) -> Dict[str, Any]:
    """Binance Futures Open Interest verisi"""
    if not OI_ENGINE_ENABLED:
        return {"enabled": False, "oi": 0, "oi_change_pct": 0}

    symbol = normalize_binance_symbol(symbol)
    cache_key = f"OI:{symbol}"
    cached = oi_cache.get(cache_key)
    now_ts = time.time()
    if cached and now_ts - cached[0] <= OI_CACHE_SEC:
        return cached[1]

    try:
        data = await asyncio.to_thread(
            _binance_fapi_get,
            "/fapi/v1/openInterest",
            {"symbol": symbol}
        )
        oi = safe_float(data.get("openInterest", 0))
        result = {"enabled": True, "oi": oi, "timestamp": now_ts}
        oi_cache[cache_key] = (now_ts, result)
        return result
    except Exception as e:
        logger.warning("Binance OI alınamadı %s: %s", symbol, e)
        return {"enabled": False, "oi": 0, "oi_change_pct": 0}


async def get_funding_rate(symbol: str) -> float:
    """Binance Futures Funding Rate"""
    if not FUNDING_ENGINE_ENABLED:
        return 0.0

    symbol = normalize_binance_symbol(symbol)
    cache_key = f"FUNDING:{symbol}"
    cached = funding_cache.get(cache_key)
    now_ts = time.time()
    if cached and now_ts - cached[0] <= FUNDING_CACHE_SEC:
        return cached[1]

    try:
        data = await asyncio.to_thread(
            _binance_fapi_get,
            "/fapi/v1/premiumIndex",
            {"symbol": symbol}
        )
        rate = safe_float(data.get("lastFundingRate", 0)) * 100.0
        funding_cache[cache_key] = (now_ts, rate)
        return rate
    except Exception as e:
        logger.warning("Binance Funding alınamadı %s: %s", symbol, e)
        return 0.0
# =========================================================
# V6 WHALE EYE MOTORLARI
# =========================================================

async def analyze_whale_eye_open_interest(
    symbol: str,
    price: float,
    price_change_5m: float,
    direction: str = "SHORT"
) -> Dict[str, Any]:
    """
    OPEN INTEREST DELTA ANALİZİ
    Balinaların gerçek pozisyon değişimini OI-Price uyumsuzluğundan okur.

    DÖRT SENARYO:
    1. Fiyat DÜŞÜYOR + OI ARTIYOR = Balinalar SHORT açıyor (En güçlü SHORT sinyali)
    2. Fiyat YÜKSELİYOR + OI DÜŞÜYOR = Balinalar LONG kapıyor (TEPE sinyali)
    3. Fiyat DÜŞÜYOR + OI DÜŞÜYOR = Long likidasyonu (Panik, trend devam edebilir)
    4. Fiyat YÜKSELİYOR + OI ARTIYOR = Yeni LONG girişi (Trend devam)
    """
    if not OI_ENGINE_ENABLED:
        return {"enabled": False, "score": 0, "divergence_type": "KAPALI", "reason": "OI motoru kapalı"}

    oi_data = await get_open_interest(symbol)
    if not oi_data.get("enabled"):
        return {"enabled": False, "score": 0, "divergence_type": "VERI_YOK", "reason": "OI verisi alınamadı"}

    # Önceki OI değerini memory'den al
    oi_memory_key = f"oi_history:{symbol}"
    prev_oi_rec = memory.get("signals", {}).get(oi_memory_key, {})
    prev_oi = safe_float(prev_oi_rec.get("oi", 0))
    prev_price = safe_float(prev_oi_rec.get("price", 0))
    current_oi = safe_float(oi_data.get("oi", 0))

    # Şimdiki OI'yi kaydet
    memory.setdefault("signals", {})[oi_memory_key] = {
        "oi": current_oi,
        "price": price,
        "ts": time.time()
    }

    if prev_oi <= 0 or prev_price <= 0:
        return {
            "enabled": True,
            "score": 0,
            "divergence_type": "BEKLIYOR",
            "reason": f"OI takip başladı. Güncel OI: {current_oi:,.0f}",
            "current_oi": current_oi,
            "prev_oi": 0,
            "oi_change_pct": 0,
            "price_change_pct": 0
        }

    oi_change_pct = pct_change(prev_oi, current_oi)
    price_change_pct = pct_change(prev_price, price)

    score = 0.0
    divergence_type = "NÖTR"
    reasons: List[str] = []

    # SENARYO 1: Fiyat düşüyor, OI artıyor = BALİNA SHORT AÇIYOR
    if price_change_pct <= -OI_BEARISH_PRICE_DROP_PCT and oi_change_pct >= OI_MIN_CHANGE_PCT:
        divergence_type = "BALINA_SHORT_ACIYOR"
        score += 12.0
        reasons.append(f"🐋 Fiyat %{price_change_pct:.2f} düşerken OI %{oi_change_pct:.2f} arttı")
        reasons.append("Balinalar agresif short açıyor - en güçlü short sinyali")
        stats["oi_short_diverge"] += 1

    # SENARYO 2: Fiyat yükseliyor, OI düşüyor = BALİNA LONG KAPATIYOR (TEPE)
    elif price_change_pct >= OI_BULLISH_PRICE_RISE_PCT and oi_change_pct <= -OI_MIN_CHANGE_PCT:
        divergence_type = "BALINA_LONG_KAPATIYOR"
        score += 10.0
        reasons.append(f"🐋 Fiyat %{price_change_pct:.2f} yükselirken OI %{oi_change_pct:.2f} düştü")
        reasons.append("Balinalar long pozisyonlarını zirvede kapatıyor - TEPE uyarısı")
        stats["oi_short_diverge"] += 1

    # SENARYO 3: Fiyat düşüyor, OI düşüyor = Long likidasyonu
    elif price_change_pct <= -OI_BEARISH_PRICE_DROP_PCT and oi_change_pct <= -OI_MIN_CHANGE_PCT:
        divergence_type = "LONG_LIKIDASYONU"
        score += 4.0
        reasons.append(f"📉 Fiyat %{price_change_pct:.2f} düşerken OI %{oi_change_pct:.2f} düştü - Long'lar likidite oluyor")

    # SENARYO 4: Fiyat yükseliyor, OI artıyor = Yeni long girişi
    elif price_change_pct >= OI_BULLISH_PRICE_RISE_PCT and oi_change_pct >= OI_MIN_CHANGE_PCT:
        divergence_type = "YENI_LONG_GIRISI"
        score += 2.0
        reasons.append(f"📈 Fiyat %{price_change_pct:.2f} yükselirken OI %{oi_change_pct:.2f} arttı - Yeni long pozisyonları")

    if direction == "LONG":
        # Long için tersine çevir
        if divergence_type == "BALINA_SHORT_ACIYOR":
            score = -8.0  # Long için negatif
        elif divergence_type == "BALINA_LONG_KAPATIYOR":
            score = -6.0
        elif divergence_type == "LONG_LIKIDASYONU":
            score = 8.0  # Long'lar likidite oldu, dipten long fırsatı
            divergence_type = "LONG_FIRSATI_LIKIDASYON_SONRASI"
            stats["oi_long_diverge"] += 1

    return {
        "enabled": True,
        "score": round(score, 2),
        "divergence_type": divergence_type,
        "reason": " | ".join(reasons) if reasons else "OI fiyat uyumlu, balina izi yok",
        "current_oi": current_oi,
        "prev_oi": prev_oi,
        "oi_change_pct": round(oi_change_pct, 2),
        "price_change_pct": round(price_change_pct, 2)
    }


async def analyze_whale_eye_funding(
    symbol: str,
    price: float,
    direction: str = "SHORT"
) -> Dict[str, Any]:
    """
    FUNDING RATE DEDEKTÖRÜ
    Aşırı fonlama oranları ters işlem fırsatıdır.

    - Funding > 0.05% = Perakende aşırı LONG = SHORT fırsatı
    - Funding > 0.10% = EKSTREM perakende LONG = Güçlü SHORT fırsatı
    - Funding < -0.03% = Perakende aşırı SHORT = LONG fırsatı
    """
    if not FUNDING_ENGINE_ENABLED:
        return {"enabled": False, "score": 0, "funding_signal": "KAPALI", "reason": "Funding motoru kapalı"}

    rate = await get_funding_rate(symbol)

    if rate == 0.0:
        return {"enabled": False, "score": 0, "funding_signal": "VERI_YOK", "reason": "Funding verisi alınamadı"}

    score = 0.0
    signal = "NÖTR"
    reasons: List[str] = []

    if direction == "SHORT":
        if rate >= FUNDING_EXTREME_THRESHOLD:
            score += FUNDING_EXTREME_SHORT_BONUS
            signal = "EKSTREM_SHORT_FIRSATI"
            reasons.append(f"🚨 Funding %{rate:.4f} - Perakende aşırı LONG sıkışmış")
            reasons.append("Balinalar short açıp funding toplar - YÜKSEK SHORT FıRSATI")
            stats["funding_short_bonus"] += 1
        elif rate >= FUNDING_SHORT_THRESHOLD:
            score += FUNDING_SHORT_BONUS
            signal = "SHORT_FIRSATI"
            reasons.append(f"⚠️ Funding %{rate:.4f} - Perakende long tarafında kalabalık")
            reasons.append("Funding pozitif = Short'lara ödeme yapılıyor - SHORT fırsatı")
            stats["funding_short_bonus"] += 1
        elif rate <= FUNDING_LONG_THRESHOLD:
            score -= FUNDING_LONG_BONUS
            signal = "LONG_AGIRLIKLI"
            reasons.append(f"🔻 Funding %{rate:.4f} - Negatif = Short'lar ödüyor")
    else:  # LONG
        if rate <= -FUNDING_EXTREME_THRESHOLD:
            score += FUNDING_EXTREME_LONG_BONUS
            signal = "EKSTREM_LONG_FIRSATI"
            reasons.append(f"🚨 Funding %{rate:.4f} - Perakende aşırı SHORT sıkışmış")
            stats["funding_long_bonus"] += 1
        elif rate <= FUNDING_LONG_THRESHOLD:
            score += FUNDING_LONG_BONUS
            signal = "LONG_FIRSATI"
            reasons.append(f"⚠️ Funding %{rate:.4f} - Short tarafında kalabalık")
            stats["funding_long_bonus"] += 1
        elif rate >= FUNDING_SHORT_THRESHOLD:
            score -= FUNDING_SHORT_BONUS
            signal = "SHORT_AGIRLIKLI"
            reasons.append(f"🔺 Funding %{rate:.4f} - Pozitif = Long'lar ödüyor")

    return {
        "enabled": True,
        "score": round(score, 2),
        "funding_rate": round(rate, 4),
        "funding_signal": signal,
        "reason": " | ".join(reasons) if reasons else f"Funding nötr %{rate:.4f}"
    }


async def analyze_whale_eye_spoofing(
    symbol: str,
    price: float,
    direction: str = "SHORT"
) -> Dict[str, Any]:
    """
    ORDERBOOK SPOOFING DEDEKTÖRÜ
    Sahte büyük emirleri (spoofing) tespit eder.

    - Büyük alış duvarı konup aniden çekilmesi = Satıcı tuzağı
    - Büyük satış duvarı konup aniden çekilmesi = Alıcı tuzağı
    - Sürekli yenilenen duvar = Gerçek arz/talep
    """
    if not SPOOFING_ENGINE_ENABLED:
        return {"enabled": False, "score": 0, "spoofing_detected": False, "spoof_type": "KAPALI"}

    symbol_okx = normalize_symbol(symbol)
    cache_key = f"SPOOF:{symbol_okx}"
    cached = orderbook_cache.get(cache_key)
    now_ts = time.time()

    # Güncel orderbook al
    try:
        book = await get_okx_orderbook(symbol_okx, 100)
        if not book.get("ok"):
            return {"enabled": True, "score": 0, "spoofing_detected": False, "spoof_type": "VERI_YOK", "reason": "Orderbook alınamadı"}
    except Exception:
        return {"enabled": True, "score": 0, "spoofing_detected": False, "spoof_type": "VERI_YOK", "reason": "Orderbook hatası"}

    prev_spoof = spoofing_memory.get(symbol_okx, {})
    prev_bid_near = safe_float(prev_spoof.get("bid_near", 0))
    prev_ask_near = safe_float(prev_spoof.get("ask_near", 0))
    prev_ts = safe_float(prev_spoof.get("ts", 0))

    bid_near = safe_float(book.get("bid_near", 0))
    ask_near = safe_float(book.get("ask_near", 0))
    mid = safe_float(book.get("mid", price))

    time_diff = now_ts - prev_ts if prev_ts > 0 else 999

    score = 0.0
    spoof_detected = False
    spoof_type = "YOK"
    reasons: List[str] = []

    # V6.1 PRO: WebSocket book geçmişiyle gerçek duvar koy-çek davranışı
    hist = list(ws_book_history.get(symbol_okx, []))
    if PRO_WS_ENABLED and len(hist) >= 3:
        recent = [h for h in hist if now_ts - safe_float(h.get("ts", 0)) <= PRO_WS_SPOOF_WINDOW_SEC]
        if len(recent) >= 2:
            max_bid = max(safe_float(h.get("bid_near", 0)) for h in recent)
            min_bid = min(safe_float(h.get("bid_near", 0)) for h in recent)
            max_ask = max(safe_float(h.get("ask_near", 0)) for h in recent)
            min_ask = min(safe_float(h.get("ask_near", 0)) for h in recent)
            if max_bid > 0 and min_bid < max_bid * PRO_WS_SPOOF_MIN_DROP_RATIO:
                spoof_detected = True
                spoof_type = "WS_ALIS_DUVARI_CEKILDI"
                if direction == "SHORT":
                    score += SPOOFING_SHORT_SCORE_BONUS * 1.25
                reasons.append("🪤 WS: alış duvarı kısa sürede çekildi, sahte destek izi")
                stats["ws_spoofing_detected"] = stats.get("ws_spoofing_detected", 0) + 1
            if max_ask > 0 and min_ask < max_ask * PRO_WS_SPOOF_MIN_DROP_RATIO:
                spoof_detected = True
                spoof_type = "WS_SATIS_DUVARI_CEKILDI"
                if direction == "LONG":
                    score += SPOOFING_LONG_SCORE_BONUS * 1.25
                reasons.append("🪤 WS: satış duvarı kısa sürede çekildi, sahte direnç izi")
                stats["ws_spoofing_detected"] = stats.get("ws_spoofing_detected", 0) + 1
            if min_ask > 0 and max_ask > min_ask * PRO_WS_SPOOF_MIN_GROWTH_RATIO and direction == "SHORT":
                score += SPOOFING_SHORT_SCORE_BONUS * 0.55
                reasons.append("🧱 WS: üst satış duvarı hızlı büyüdü")
            if min_bid > 0 and max_bid > min_bid * PRO_WS_SPOOF_MIN_GROWTH_RATIO and direction == "LONG":
                score += SPOOFING_LONG_SCORE_BONUS * 0.55
                reasons.append("🧱 WS: alt alış duvarı hızlı büyüdü")

    # Alış duvarı aniden kayboldu mu? (Spoofing - satıcı tuzağı)
    if prev_bid_near > 0 and bid_near < prev_bid_near * 0.4 and time_diff <= SPOOFING_WALL_VANISH_SEC:
        spoof_detected = True
        spoof_type = "ALIS_DUVARI_KAYBOLDU"
        if direction == "SHORT":
            score += SPOOFING_SHORT_SCORE_BONUS
        reasons.append(f"🪤 Büyük alış duvarı {time_diff:.1f}s içinde kayboldu - Sahte destek!")
        reasons.append("Satıcılar alıcıları tuzağa çekip short açıyor")
        stats["spoofing_detected"] += 1

    # Satış duvarı aniden kayboldu mu? (Alıcı tuzağı)
    if prev_ask_near > 0 and ask_near < prev_ask_near * 0.4 and time_diff <= SPOOFING_WALL_VANISH_SEC:
        spoof_detected = True
        spoof_type = "SATIS_DUVARI_KAYBOLDU"
        if direction == "LONG":
            score += SPOOFING_LONG_SCORE_BONUS
        reasons.append(f"🪤 Büyük satış duvarı {time_diff:.1f}s içinde kayboldu - Sahte direnç!")
        stats["spoofing_detected"] += 1

    # Ani satış duvarı yığılması
    if prev_ask_near > 0 and ask_near > prev_ask_near * SPOOFING_MIN_WALL_SIZE_MULT and time_diff <= 5.0:
        if direction == "SHORT":
            score += SPOOFING_SHORT_SCORE_BONUS * 0.7
        reasons.append(f"🧱 Satış duvarı aniden %{pct_change(prev_ask_near, ask_near):.0f} büyüdü")
        stats["spoofing_detected"] += 1

    # Hafızaya kaydet
    spoofing_memory[symbol_okx] = {
        "ts": now_ts,
        "bid_near": bid_near,
        "ask_near": ask_near,
        "mid": mid
    }

    return {
        "enabled": True,
        "score": round(score, 2),
        "spoofing_detected": spoof_detected,
        "spoof_type": spoof_type,
        "reason": " | ".join(reasons) if reasons else "Orderbook temiz, spoofing yok",
        "bid_near": bid_near,
        "ask_near": ask_near
    }


async def analyze_whale_eye_cvd(
    symbol: str,
    price: float,
    k1: List[List[Any]],
    direction: str = "SHORT"
) -> Dict[str, Any]:
    """
    CUMULATIVE VOLUME DELTA (CVD) ANALİZİ
    Alış/satış hacim agresyonunu ölçer.

    - Fiyat yükseliyor ama CVD düşüyor = Bearish divergence (SHORT fırsatı)
    - Fiyat düşüyor ama CVD yükseliyor = Bullish divergence (LONG fırsatı)
    """
    if not CVD_ENGINE_ENABLED or len(k1) < CVD_LOOKBACK_MIN:
        return {"enabled": False, "score": 0, "divergence": "KAPALI", "reason": "CVD kapalı veya veri yetersiz"}

    # Basitleştirilmiş CVD: Her mumun alış/satış yönünü body'den tahmin et
    cvd = 0.0
    cvd_history: List[float] = []
    price_history: List[float] = []

    lookback = min(CVD_LOOKBACK_MIN, len(k1) - 5)
    for i in range(len(k1) - lookback, len(k1)):
        k = k1[i]
        o = safe_float(k[1])
        c = safe_float(k[4])
        v = safe_float(k[5])
        body = c - o

        if body > 0:
            cvd += v  # Alış hacmi
        elif body < 0:
            cvd -= v  # Satış hacmi

        cvd_history.append(cvd)
        price_history.append(c)

    if len(cvd_history) < 10 or len(price_history) < 10:
        return {"enabled": True, "score": 0, "divergence": "VERI_YOK", "reason": "CVD verisi yetersiz"}

    # CVD trendi
    cvd_first = avg(cvd_history[:5])
    cvd_last = avg(cvd_history[-5:])
    price_first = avg(price_history[:5])
    price_last = avg(price_history[-5:])

    cvd_trend = pct_change(cvd_first, cvd_last)
    price_trend = pct_change(price_first, price_last)

    score = 0.0
    divergence = "NÖTR"
    reasons: List[str] = []

    # Bearish divergence: Fiyat yükseliyor, CVD düşüyor
    if price_trend > 0.3 and cvd_trend < -0.5:
        divergence = "BEARISH_DIVERGENCE"
        if direction == "SHORT":
            score += CVD_SHORT_DIVERGENCE_SCORE
        reasons.append(f"📉 Bearish: Fiyat %{price_trend:.2f}↑ ama CVD %{cvd_trend:.2f}↓ - Satış baskısı gizli")
        stats["cvd_diverge_short"] += 1

    # Bullish divergence: Fiyat düşüyor, CVD yükseliyor
    elif price_trend < -0.3 and cvd_trend > 0.5:
        divergence = "BULLISH_DIVERGENCE"
        if direction == "LONG":
            score += CVD_LONG_DIVERGENCE_SCORE
        reasons.append(f"📈 Bullish: Fiyat %{price_trend:.2f}↓ ama CVD %{cvd_trend:.2f}↑ - Alış baskısı gizli")
        stats["cvd_diverge_long"] += 1

    return {
        "enabled": True,
        "score": round(score, 2),
        "divergence": divergence,
        "cvd_trend_pct": round(cvd_trend, 2),
        "price_trend_pct": round(price_trend, 2),
        "reason": " | ".join(reasons) if reasons else "CVD fiyatla uyumlu"
    }


async def build_full_whale_eye_analysis(
    symbol: str,
    price: float,
    price_change_5m: float,
    k1: List[List[Any]],
    direction: str = "SHORT"
) -> Dict[str, Any]:
    """
    TÜM WHALE EYE MOTORLARINI BIRLEŞTIREN ANA FONKSIYON.
    OI + Funding + Spoofing + CVD = Gerçek balina izi.
    """
    oi = await analyze_whale_eye_open_interest(symbol, price, price_change_5m, direction)
    funding = await analyze_whale_eye_funding(symbol, price, direction)
    spoofing = await analyze_whale_eye_spoofing(symbol, price, direction)
    cvd = await analyze_whale_eye_cvd(symbol, price, k1, direction)

    total_score = (
        safe_float(oi.get("score", 0)) +
        safe_float(funding.get("score", 0)) +
        safe_float(spoofing.get("score", 0)) +
        safe_float(cvd.get("score", 0))
    )

    divergence_types = []
    direction_u = (direction or "SHORT").upper()

    oi_div = oi.get("divergence_type", "NÖTR")
    if oi_div not in ("NÖTR", "BEKLIYOR", "KAPALI", "VERI_YOK"):
        # OI fonksiyonu direction'a göre puanı zaten tersliyor; pozitif skor varsa güvene dahil et.
        if safe_float(oi.get("score", 0)) > 0:
            divergence_types.append(oi_div)

    funding_sig = funding.get("funding_signal", "NÖTR")
    if funding_sig not in ("NÖTR", "KAPALI", "VERI_YOK"):
        if safe_float(funding.get("score", 0)) > 0:
            divergence_types.append(funding_sig)

    if spoofing.get("spoofing_detected"):
        # Karışık/ters spoofing izi güveni şişirmesin; sadece yön lehine pozitif skor varsa güvene dahil et.
        if safe_float(spoofing.get("score", 0)) > 0:
            divergence_types.append(spoofing.get("spoof_type", "SPOOF"))

    cvd_div = cvd.get("divergence", "NÖTR")
    if cvd_div not in ("NÖTR", "KAPALI", "VERI_YOK"):
        # SHORT için sadece BEARISH_DIVERGENCE, LONG için sadece BULLISH_DIVERGENCE güveni artırır.
        if direction_u == "SHORT" and cvd_div == "BEARISH_DIVERGENCE":
            divergence_types.append(cvd_div)
        elif direction_u == "LONG" and cvd_div == "BULLISH_DIVERGENCE":
            divergence_types.append(cvd_div)

    whale_confidence = "DÜŞÜK"
    if len(divergence_types) >= 3:
        whale_confidence = "ÇOK_YÜKSEK"
    elif len(divergence_types) >= 2:
        whale_confidence = "YÜKSEK"
    elif len(divergence_types) >= 1:
        whale_confidence = "ORTA"

    all_reasons = []
    for r in [oi.get("reason", ""), funding.get("reason", ""), spoofing.get("reason", ""), cvd.get("reason", "")]:
        if r and r != "NÖTR":
            all_reasons.append(r)

    return {
        "enabled": True,
        "total_score": round(total_score, 2),
        "whale_confidence": whale_confidence,
        "divergence_count": len(divergence_types),
        "divergence_types": divergence_types,
        "oi": oi,
        "funding": funding,
        "spoofing": spoofing,
        "cvd": cvd,
        "reason": " | ".join(all_reasons) if all_reasons else "Balina izi tespit edilmedi"
    }
# =========================================================
# TELEGRAM GÖNDERİMİ
# =========================================================
def _telegram_api_send(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Telegram token/chat_id eksik")
        stats["telegram_fail"] += 1
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    session = _get_session()
    resp = session.post(url, data=payload, timeout=HTTP_TIMEOUT)
    ok = resp.status_code == 200 and resp.json().get("ok") is True
    if not ok:
        logger.error("Telegram API hata: code=%s body=%s", resp.status_code, resp.text[:500])
    return ok


async def safe_send_telegram(text: str, retry: int = 3, delay_sec: float = 1.5) -> bool:
    for i in range(1, retry + 1):
        try:
            ok = await asyncio.to_thread(_telegram_api_send, text)
            if ok:
                return True
        except Exception as e:
            logger.exception("Telegram gönderim hatası deneme %s/%s: %s", i, retry, e)
        await asyncio.sleep(delay_sec * i)
    stats["telegram_fail"] += 1
    return False


# =========================================================
# OKX DATA
# =========================================================
def normalize_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper().replace("/", "-")
    if s.endswith("-SWAP"):
        return s
    if s.endswith("USDT") and "-" not in s:
        base = s[:-4]
        return f"{base}-USDT-SWAP"
    if s.endswith("-USDT"):
        return f"{s}-SWAP"
    if "-" not in s:
        return f"{s}-USDT-SWAP"
    return s


def _okx_get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    url = f"{OKX_BASE_URL}{path}"
    session = _get_session()
    resp = session.get(url, params=params or {}, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if str(data.get("code", "1")) != "0":
        raise RuntimeError(f"OKX hata: code={data.get('code')} msg={data.get('msg')}")
    return data.get("data", [])


def _okx_to_kline(row: List[Any]) -> List[Any]:
    return [
        row[0], row[1], row[2], row[3], row[4], row[5],
        row[6] if len(row) > 6 else row[5],
        row[7] if len(row) > 7 else row[6] if len(row) > 6 else row[5],
        row[8] if len(row) > 8 else "1",
    ]


async def get_okx_instruments(force: bool = False) -> Dict[str, Dict[str, Any]]:
    cached = instrument_cache.get("okx_instruments")
    now_ts = time.time()
    if cached and not force and now_ts - cached[0] <= OKX_INSTRUMENT_CACHE_SEC:
        return cached[1]
    try:
        data = await asyncio.to_thread(_okx_get, "/api/v5/public/instruments", {"instType": OKX_INST_TYPE})
        mp: Dict[str, Dict[str, Any]] = {}
        for row in data:
            inst_id = str(row.get("instId", "")).upper().strip()
            state = str(row.get("state", "live")).lower().strip()
            if not inst_id:
                continue
            if state and state not in ("live", "normal"):
                continue
            mp[inst_id] = row
        instrument_cache["okx_instruments"] = (now_ts, mp)
        return mp
    except Exception as e:
        stats["api_fail"] += 1
        logger.warning("OKX instruments alınamadı: %s", e)
        return cached[1] if cached else {}


async def refresh_coin_pool(force: bool = False) -> Tuple[int, int]:
    global COINS, okx_live_symbols
    instruments = await get_okx_instruments(force=force)
    if not instruments:
        return len(COINS), stats.get("okx_symbol_pruned", 0)

    okx_live_symbols.clear()
    okx_live_symbols.update(instruments)

    valid: List[str] = []
    invalid: List[str] = []
    seen = set()
    for sym in COINS:
        ns = normalize_symbol(sym)
        if is_blocked_coin_symbol(ns):
            invalid.append(ns)
            stats["blocked_coin_skip"] += 1
            continue
        if ns in seen:
            continue
        seen.add(ns)
        if ns in instruments:
            valid.append(ns)
        else:
            invalid.append(ns)

    if valid:
        COINS = valid

    stats["okx_symbol_refresh"] += 1
    stats["okx_symbol_pruned"] = len(invalid)

    if invalid:
        logger.warning("OKX dışı/pasif coinler çıkarıldı: %s", ", ".join(invalid[:20]))
    logger.info("Aktif coin havuzu yenilendi | aktif=%s | çıkarılan=%s", len(COINS), len(invalid))
    return len(COINS), len(invalid)


async def symbol_refresh_loop() -> None:
    while True:
        try:
            await refresh_coin_pool(force=True)
        except Exception as e:
            logger.exception("symbol_refresh_loop hata: %s", e)
        await asyncio.sleep(max(300, AUTO_SYMBOL_REFRESH_SEC))


async def get_klines(symbol: str, interval: str, limit: int = 120) -> List[List[Any]]:
    symbol = normalize_symbol(symbol)

    if okx_live_symbols and symbol not in okx_live_symbols:
        stats["invalid_symbol_skip"] += 1
        return []

    if symbol_temporarily_blocked(symbol):
        stats["blocked_symbol_skip"] += 1
        return []

    cache_key = f"{symbol}:{interval}:{limit}"
    cached = kline_cache.get(cache_key)
    now_ts = time.time()
    if cached and now_ts - cached[0] <= KLINE_CACHE_SEC:
        return cached[1]
    try:
        data = await asyncio.to_thread(
            _okx_get,
            "/api/v5/market/candles",
            {"instId": symbol, "bar": interval, "limit": min(limit, 300)},
        )
        rows = [_okx_to_kline(x) for x in reversed(data)]
        if not rows:
            stats["api_fail"] += 1
            note_symbol_fail(symbol, f"{interval}:empty")
            return []
        note_symbol_success(symbol)
        kline_cache[cache_key] = (now_ts, rows)
        return rows
    except Exception as e:
        stats["api_fail"] += 1
        note_symbol_fail(symbol, f"{interval}:{e}")
        logger.warning("OKX kline alınamadı %s %s: %s", symbol, interval, e)
        return []


async def get_24h_tickers() -> Dict[str, Dict[str, Any]]:
    cached = ticker_cache.get("24hr")
    now_ts = time.time()
    if cached and now_ts - cached[0] <= TICKER_CACHE_SEC:
        return cached[1]
    try:
        data = await asyncio.to_thread(_okx_get, "/api/v5/market/tickers", {"instType": OKX_INST_TYPE})
        mp = {str(x.get("instId", "")).upper(): x for x in data if x.get("instId")}
        ticker_cache["24hr"] = (now_ts, mp)
        return mp
    except Exception as e:
        stats["api_fail"] += 1
        logger.warning("OKX 24h ticker alınamadı: %s", e)
        return cached[1] if cached else {}



# =========================================================
# V6.1 PRO WEBSOCKET CANLI VERİ MOTORU
# =========================================================
def _book_metrics_from_rows(symbol: str, bids: List[List[Any]], asks: List[List[Any]], source: str = "REST") -> Dict[str, Any]:
    symbol = normalize_symbol(symbol)
    if not bids or not asks:
        return {"enabled": True, "ok": False, "source": source, "reason": "empty bids/asks"}
    best_bid = safe_float(bids[0][0])
    best_ask = safe_float(asks[0][0])
    mid = (best_bid + best_ask) / 2.0 if best_bid > 0 and best_ask > 0 else 0.0
    band = mid * 0.0018 if mid > 0 else 0.0
    bid_near = ask_near = bid_total = ask_total = 0.0
    for row in bids:
        px = safe_float(row[0]); sz = safe_float(row[1]); notional = px * sz
        bid_total += notional
        if mid > 0 and px >= mid - band:
            bid_near += notional
    for row in asks:
        px = safe_float(row[0]); sz = safe_float(row[1]); notional = px * sz
        ask_total += notional
        if mid > 0 and px <= mid + band:
            ask_near += notional
    total_near = bid_near + ask_near
    book_pressure = ((ask_near - bid_near) / total_near) if total_near > 0 else 0.0
    total_all = bid_total + ask_total
    full_book_pressure = ((ask_total - bid_total) / total_all) if total_all > 0 else 0.0
    prev = orderbook_memory.get(symbol, {})
    prev_bid_near = safe_float(prev.get("bid_near", 0))
    prev_ask_near = safe_float(prev.get("ask_near", 0))
    bid_wall_pulled = prev_bid_near > 0 and bid_near < prev_bid_near * 0.58
    ask_wall_stacked = prev_ask_near > 0 and ask_near > prev_ask_near * 1.35
    bid_wall_added = prev_bid_near > 0 and bid_near > prev_bid_near * 1.35
    ask_wall_pulled = prev_ask_near > 0 and ask_near < prev_ask_near * 0.58
    orderbook_memory[symbol] = {
        "ts": time.time(), "bid_near": bid_near, "ask_near": ask_near,
        "bid_total": bid_total, "ask_total": ask_total,
        "book_pressure": book_pressure, "full_book_pressure": full_book_pressure,
    }
    return {
        "enabled": True, "ok": True, "source": source,
        "best_bid": best_bid, "best_ask": best_ask, "mid": mid,
        "spread_pct": abs(pct_change(best_bid, best_ask)) if best_bid > 0 and best_ask > 0 else 0.0,
        "bid_near": bid_near, "ask_near": ask_near, "bid_total": bid_total, "ask_total": ask_total,
        "book_pressure": round(book_pressure, 4), "full_book_pressure": round(full_book_pressure, 4),
        "bid_wall_pulled": bid_wall_pulled, "ask_wall_stacked": ask_wall_stacked,
        "bid_wall_added": bid_wall_added, "ask_wall_pulled": ask_wall_pulled,
        "reason": f"OKX orderbook {source} okundu.",
    }


def _ws_symbol_list() -> List[str]:
    symbols = [normalize_symbol(s) for s in COINS if not is_blocked_coin_symbol(s)]
    if PRO_WS_SYMBOL_LIMIT > 0:
        symbols = symbols[:PRO_WS_SYMBOL_LIMIT]
    return symbols


async def okx_public_ws_loop() -> None:
    if not PRO_WS_ENABLED:
        return
    if websockets is None:
        ws_runtime_state["last_error"] = "websockets paketi yok"
        logger.warning("WebSocket kapalı: websockets paketi yok")
        return
    while True:
        try:
            symbols = _ws_symbol_list()
            if not symbols:
                await asyncio.sleep(10)
                continue
            args = []
            for sym in symbols:
                args.append({"channel": PRO_WS_BOOK_CHANNEL, "instId": sym})
                args.append({"channel": PRO_WS_TRADE_CHANNEL, "instId": sym})
            async with websockets.connect(PRO_WS_URL, ping_interval=20, ping_timeout=20, close_timeout=10, max_size=4_000_000) as ws:
                ws_runtime_state.update({"connected": True, "last_error": "-", "subscriptions": len(args)})
                await ws.send(json.dumps({"op": "subscribe", "args": args}))
                logger.info("OKX WS bağlandı | sembol=%s | kanal=%s", len(symbols), len(args))
                async for raw in ws:
                    ws_runtime_state["last_msg_ts"] = time.time()
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        continue
                    if "event" in msg:
                        continue
                    arg = msg.get("arg", {}) or {}
                    channel = str(arg.get("channel", ""))
                    inst_id = normalize_symbol(str(arg.get("instId", "")))
                    data = msg.get("data", []) or []
                    if not inst_id or not data:
                        continue
                    if channel == PRO_WS_BOOK_CHANNEL:
                        item = data[0]
                        bids = item.get("bids", []) or []
                        asks = item.get("asks", []) or []
                        metrics = _book_metrics_from_rows(inst_id, bids, asks, "WS")
                        ws_orderbooks[inst_id] = {"ts": time.time(), "bids": bids, "asks": asks, "metrics": metrics}
                        hist = ws_book_history.setdefault(inst_id, deque(maxlen=max(10, PRO_WS_BOOK_HISTORY)))
                        hist.append({"ts": time.time(), "bid_near": metrics.get("bid_near", 0), "ask_near": metrics.get("ask_near", 0), "pressure": metrics.get("book_pressure", 0)})
                        stats["ws_book_updates"] = stats.get("ws_book_updates", 0) + 1
                    elif channel == PRO_WS_TRADE_CHANNEL:
                        dq = ws_trades.setdefault(inst_id, deque(maxlen=max(20, PRO_WS_TRADE_HISTORY)))
                        for t in data:
                            dq.append({"px": safe_float(t.get("px", 0)), "sz": safe_float(t.get("sz", 0)), "side": str(t.get("side", "")).lower(), "ts": safe_float(t.get("ts", 0))})
                            stats["ws_trade_updates"] = stats.get("ws_trade_updates", 0) + 1
        except asyncio.CancelledError:
            ws_runtime_state["connected"] = False
            raise
        except Exception as e:
            ws_runtime_state["connected"] = False
            ws_runtime_state["last_error"] = str(e)[:180]
            ws_runtime_state["reconnects"] = int(ws_runtime_state.get("reconnects", 0)) + 1
            logger.warning("OKX WS koptu, yeniden bağlanacak: %s", e)
            await asyncio.sleep(max(1.0, PRO_WS_RECONNECT_SEC))


def ws_is_fresh(symbol: str) -> bool:
    symbol = normalize_symbol(symbol)
    rec = ws_orderbooks.get(symbol)
    return bool(rec and time.time() - safe_float(rec.get("ts", 0)) <= PRO_WS_STALE_SEC)


async def get_okx_orderbook(symbol: str, depth: int = 50) -> Dict[str, Any]:
    if not GORUNMEYEN_YUZ_ORDERBOOK_ENABLED:
        return {"enabled": False, "ok": False, "reason": "Orderbook motoru kapalı."}

    symbol = normalize_symbol(symbol)
    now_ts = time.time()

    # Öncelik: WebSocket canlı book
    if PRO_WS_ENABLED:
        ws_rec = ws_orderbooks.get(symbol)
        if ws_rec and now_ts - safe_float(ws_rec.get("ts", 0)) <= PRO_WS_STALE_SEC:
            metrics = copy.deepcopy(ws_rec.get("metrics", {}))
            if metrics:
                metrics["source"] = "WS"
                metrics["reason"] = "OKX orderbook WS canlı akıştan okundu."
                stats["orderbook_ok"] += 1
                return metrics

    cache_key = f"BOOK:{symbol}:{depth}"
    cached = orderbook_cache.get(cache_key)
    if cached and now_ts - cached[0] <= GORUNMEYEN_YUZ_BOOK_CACHE_SEC:
        return cached[1]

    try:
        data = await asyncio.to_thread(
            _okx_get,
            "/api/v5/market/books",
            {"instId": symbol, "sz": min(max(depth, 5), 400)},
        )
        if not data:
            raise RuntimeError("empty book")
        book = data[0]
        bids = book.get("bids", []) or []
        asks = book.get("asks", []) or []
        result = _book_metrics_from_rows(symbol, bids, asks, "REST")
        if not result.get("ok"):
            raise RuntimeError(result.get("reason", "empty bids/asks"))
        orderbook_cache[cache_key] = (now_ts, result)
        stats["orderbook_ok"] += 1
        return result
    except Exception as e:
        stats["orderbook_fail"] += 1
        logger.warning("OKX orderbook alınamadı %s: %s", symbol, e)
        return {"enabled": True, "ok": False, "reason": f"Orderbook alınamadı: {e}"}


async def get_okx_recent_trades(symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
    if not GORUNMEYEN_YUZ_TRADES_ENABLED:
        return []

    symbol = normalize_symbol(symbol)
    now_ts = time.time()

    # Öncelik: WebSocket canlı trades
    if PRO_WS_ENABLED:
        dq = ws_trades.get(symbol)
        if dq:
            rows = list(dq)[-min(limit, len(dq)):]
            if rows:
                newest_ts = max(safe_float(x.get("ts", 0)) for x in rows) / 1000.0
                if newest_ts <= 0 or now_ts - newest_ts <= max(PRO_WS_STALE_SEC * 3, 20):
                    stats["trades_ok"] += 1
                    return rows

    cache_key = f"TRADES:{symbol}:{limit}"
    cached = trades_cache.get(cache_key)
    if cached and now_ts - cached[0] <= GORUNMEYEN_YUZ_TRADE_CACHE_SEC:
        return cached[1]

    try:
        data = await asyncio.to_thread(
            _okx_get,
            "/api/v5/market/trades",
            {"instId": symbol, "limit": min(max(limit, 10), 500)},
        )
        rows: List[Dict[str, Any]] = []
        for row in data or []:
            rows.append({"px": safe_float(row.get("px", 0)), "sz": safe_float(row.get("sz", 0)), "side": str(row.get("side", "")).lower(), "ts": safe_float(row.get("ts", 0))})
        trades_cache[cache_key] = (now_ts, rows)
        stats["trades_ok"] += 1
        return rows
    except Exception as e:
        stats["trades_fail"] += 1
        logger.warning("OKX trade akışı alınamadı %s: %s", symbol, e)
        return []


def analyze_trade_flow(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    buy_notional = 0.0
    sell_notional = 0.0
    buy_count = 0
    sell_count = 0

    for t in trades:
        px = safe_float(t.get("px", 0))
        sz = safe_float(t.get("sz", 0))
        side = str(t.get("side", "")).lower()
        notional = px * sz
        if side == "buy":
            buy_notional += notional
            buy_count += 1
        elif side == "sell":
            sell_notional += notional
            sell_count += 1

    total = buy_notional + sell_notional
    sell_ratio = sell_notional / total if total > 0 else 0.0
    buy_ratio = buy_notional / total if total > 0 else 0.0
    sell_to_buy = sell_notional / max(buy_notional, 1e-9)
    buy_to_sell = buy_notional / max(sell_notional, 1e-9)

    return {
        "buy_notional": buy_notional,
        "sell_notional": sell_notional,
        "buy_count": buy_count,
        "sell_count": sell_count,
        "sell_ratio": round(sell_ratio, 4),
        "buy_ratio": round(buy_ratio, 4),
        "sell_to_buy": round(sell_to_buy, 4),
        "buy_to_sell": round(buy_to_sell, 4),
    }


def normalize_binance_symbol(symbol: str) -> str:
    s = normalize_symbol(symbol)
    parts = s.split("-")
    if len(parts) >= 2:
        return f"{parts[0]}{parts[1]}"
    return s.replace("-", "")


def _binance_get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    url = f"{BINANCE_CONFIRM_BASE_URL}{path}"
    session = _get_session()
    resp = session.get(url, params=params or {}, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


async def get_binance_klines(symbol: str, interval: str, limit: int = 120) -> List[List[Any]]:
    symbol = normalize_binance_symbol(symbol)
    cache_key = f"BIN:{symbol}:{interval}:{limit}"
    cached = kline_cache.get(cache_key)
    now_ts = time.time()
    if cached and now_ts - cached[0] <= KLINE_CACHE_SEC:
        return cached[1]
    try:
        data = await asyncio.to_thread(
            _binance_get,
            "/api/v3/klines",
            {"symbol": symbol, "interval": interval, "limit": min(limit, 1000)},
        )
        kline_cache[cache_key] = (now_ts, data)
        return data
    except Exception as e:
        logger.warning("Binance teyit kline alınamadı %s %s: %s", symbol, interval, e)
        return []


# =========================================================
# TEKNİK HESAPLAR
# =========================================================
def closes(klines: List[List[Any]]) -> List[float]:
    return [safe_float(x[4]) for x in klines]


def highs(klines: List[List[Any]]) -> List[float]:
    return [safe_float(x[2]) for x in klines]


def lows(klines: List[List[Any]]) -> List[float]:
    return [safe_float(x[3]) for x in klines]


def volumes(klines: List[List[Any]]) -> List[float]:
    return [safe_float(x[5]) for x in klines]


def ema(values: List[float], period: int) -> List[float]:
    """
    Güvenli EMA.
    Eski sürümde veri period'dan az olduğunda bütün seri avg(values) ile dolduruluyordu;
    bu da bot yeni başladığında/az veri olan coinde sahte EMA ve hatalı skor üretiyordu.
    Burada EMA ilk bardan başlar, her bar sadece o ana kadarki gerçek veriyle güncellenir.
    """
    if not values:
        return []
    if period <= 1:
        return [float(v) for v in values]
    alpha = 2.0 / (period + 1.0)
    out: List[float] = [float(values[0])]
    for v in values[1:]:
        out.append((float(v) * alpha) + (out[-1] * (1.0 - alpha)))
    return out


def rsi(values: List[float], period: int = 14) -> List[float]:
    if not values:
        return []
    if len(values) < period + 1:
        return [50.0 for _ in values]

    rsis = [50.0] * len(values)
    gains: List[float] = []
    losses: List[float] = []

    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(abs(min(diff, 0.0)))

    avg_gain = avg(gains[:period])
    avg_loss = avg(losses[:period])

    def calc_rsi(g: float, l: float) -> float:
        if l == 0 and g == 0:
            return 50.0
        if l == 0:
            return 100.0
        rs = g / l
        return 100.0 - (100.0 / (1.0 + rs))

    rsis[period] = calc_rsi(avg_gain, avg_loss)

    for i in range(period + 1, len(values)):
        gain = gains[i - 1]
        loss = losses[i - 1]
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
        rsis[i] = calc_rsi(avg_gain, avg_loss)

    return rsis


def true_ranges(klines: List[List[Any]]) -> List[float]:
    if len(klines) < 2:
        return [0.0 for _ in klines]
    trs = [0.0]
    for i in range(1, len(klines)):
        high = safe_float(klines[i][2])
        low = safe_float(klines[i][3])
        prev_close = safe_float(klines[i - 1][4])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return trs


def atr(klines: List[List[Any]], period: int = 14) -> List[float]:
    trs = true_ranges(klines)
    return ema(trs, period)


def candle_rejection_score(kline: List[Any]) -> float:
    o = safe_float(kline[1])
    h = safe_float(kline[2])
    l = safe_float(kline[3])
    c = safe_float(kline[4])
    rng = max(h - l, 1e-9)
    upper_wick = h - max(o, c)
    body = abs(c - o)
    score = 0.0
    score += clamp((upper_wick / rng) * 60.0, 0.0, 35.0)
    if c < o:
        score += 10.0
    if body / rng < 0.35:
        score += 5.0
    return score


def lower_highs(values: List[float], n: int = 3) -> bool:
    if len(values) < n:
        return False
    sub = values[-n:]
    return all(sub[i] < sub[i - 1] for i in range(1, len(sub)))


def lower_lows(values: List[float], n: int = 3) -> bool:
    if len(values) < n:
        return False
    sub = values[-n:]
    return all(sub[i] < sub[i - 1] for i in range(1, len(sub)))


def recent_red_count(klines: List[List[Any]], n: int = 5) -> int:
    if not klines:
        return 0
    part = klines[-n:]
    count = 0
    for k in part:
        if safe_float(k[4]) < safe_float(k[1]):
            count += 1
    return count


def consecutive_green_count(klines: List[List[Any]], n: int = 6) -> int:
    if not klines:
        return 0
    count = 0
    for k in reversed(klines[-n:]):
        if safe_float(k[4]) > safe_float(k[1]):
            count += 1
        else:
            break
    return count


def short_breakdown_confirmation(k1: List[List[Any]], k5: List[List[Any]]) -> Dict[str, Any]:
    if len(k1) < 30 or len(k5) < 30:
        return {"score": 0.0, "reason": "Kırılım verisi yetersiz"}

    c1 = closes(k1)
    h1 = highs(k1)
    l1 = lows(k1)
    c5 = closes(k5)
    v1 = volumes(k1)
    e9 = ema(c1, 9)
    e21 = ema(c1, 21)
    r1 = rsi(c1, 14)

    last_price = c1[-1]
    prev_k = k1[-2]
    last_k = k1[-1]
    recent_low_8 = min(l1[-9:-1])
    recent_high_12 = max(h1[-13:-1])
    prev_high_6 = max(h1[-8:-2])
    red_count = recent_red_count(k1, 5)

    score = 0.0
    reasons: List[str] = []

    if last_price < e9[-1]:
        score += 2.0
        reasons.append("EMA9 altı")
    if last_price < e21[-1]:
        score += 2.5
        reasons.append("EMA21 altı")
    if e9[-1] < e21[-1]:
        score += 2.0
        reasons.append("EMA9/21 aşağı")
    if last_price < recent_low_8:
        score += 3.0
        reasons.append("Son dip kırıldı")
    if lower_highs(h1, 3):
        score += 2.0
        reasons.append("Alçalan tepeler")
    if lower_lows(l1, 3):
        score += 2.0
        reasons.append("Alçalan dipler")
    if red_count >= MIN_RED_CANDLES_FOR_SHORT:
        score += 1.5
        reasons.append(f"Kırmızı mum {red_count}")
    if safe_float(last_k[4]) < safe_float(last_k[1]) and safe_float(prev_k[4]) < safe_float(prev_k[1]):
        score += 1.5
        reasons.append("Arka arkaya satış mumu")
    if r1[-1] < 50:
        score += 2.0
        reasons.append("RSI 50 altı")
    elif r1[-1] < r1[-2] and r1[-1] < 55:
        score += 1.0
        reasons.append("RSI düşüyor")
    if c5[-1] < c5[-2] and c5[-1] < c5[-3]:
        score += 2.0
        reasons.append("5dk kapanış zayıf")
    if safe_float(last_k[2]) >= recent_high_12 and last_price < prev_high_6:
        score += 2.5
        reasons.append("Tepe reddi")
    vol_ratio = safe_float(v1[-1]) / max(avg(v1[-20:-1]), 1e-9)
    if safe_float(last_k[4]) < safe_float(last_k[1]) and vol_ratio >= 1.25:
        score += 1.5
        reasons.append(f"Satış hacmi x{vol_ratio:.2f}")

    return {"score": round(score, 2), "reason": " | ".join(reasons[:8]) if reasons else "Net kırılım yok"}


def candle_wick_ratios(kline: List[Any]) -> Tuple[float, float, float, bool]:
    o = safe_float(kline[1])
    h = safe_float(kline[2])
    l = safe_float(kline[3])
    c = safe_float(kline[4])
    rng = max(h - l, 1e-9)
    upper = max(0.0, h - max(o, c)) / rng
    lower = max(0.0, min(o, c) - l) / rng
    body = abs(c - o) / rng
    red = c < o
    return upper, lower, body, red

def trend_continuation_guard(
    pump_10m: float,
    pump_20m: float,
    last_price: float,
    ema9: float,
    ema21: float,
    rsi1_val: float,
    rsi5_val: float,
    rej_score: float,
    weak_close: bool,
    structure_turn: bool,
    breakdown_score: float,
    red_count: int,
) -> Dict[str, Any]:
    if not TREND_GUARD_ENABLED:
        return {"blocked": False, "score": 0.0, "reason": "Trend koruması kapalı"}

    score = 0.0
    reasons: List[str] = []

    if pump_10m >= TREND_GUARD_MIN_PUMP_10M:
        score += 1.4
        reasons.append(f"10dk güçlü %{pump_10m:.2f}")
    if pump_20m >= TREND_GUARD_MIN_PUMP_20M:
        score += 1.8
        reasons.append(f"20dk güçlü %{pump_20m:.2f}")
    if last_price > ema9 > ema21:
        score += 2.0
        reasons.append("EMA9>EMA21 üstünde")
    elif last_price > ema9:
        score += 1.0
        reasons.append("EMA9 üstünde")
    if rsi1_val >= TREND_GUARD_MIN_RSI_1M:
        score += 1.0
        reasons.append(f"RSI1 güçlü {rsi1_val:.1f}")
    if rsi5_val >= TREND_GUARD_MIN_RSI_5M:
        score += 1.0
        reasons.append(f"RSI5 güçlü {rsi5_val:.1f}")
    if rej_score < 10:
        score += 0.7
        reasons.append("Tepe reddi zayıf")
    if not weak_close:
        score += 0.8
        reasons.append("Son mum zayıf kapanmadı")
    if not structure_turn:
        score += 0.8
        reasons.append("Yapı bozulmadı")
    if red_count < MIN_RED_CANDLES_FOR_SHORT:
        score += 0.7
        reasons.append("Satış mumu yetersiz")

    if breakdown_score >= TREND_BREAKDOWN_MIN_SCORE:
        score -= 3.5
        reasons.append(f"Kırılım var {breakdown_score:.1f}")

    blocked = score >= TREND_GUARD_SCORE_BLOCK and breakdown_score < TREND_BREAKDOWN_MIN_SCORE
    return {"blocked": blocked, "score": round(score, 2), "reason": " | ".join(reasons[:8])}


def calculate_short_levels(entry: float, h1: List[float], last_atr1: float, last_atr5: float) -> Tuple[float, float, float, float, float]:
    if entry <= 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0

    recent_swing_high = max(h1[-12:]) if len(h1) >= 12 else max(h1) if h1 else entry
    min_stop_dist = entry * (SHORT_MIN_STOP_PCT / 100.0)
    atr_stop_dist = max(last_atr1 * SHORT_STOP_ATR_MULT, min_stop_dist)
    structure_buffer = recent_swing_high * (SHORT_STRUCTURE_EXTRA_BUFFER_PCT / 100.0)
    wick_buffer = max(last_atr1 * SHORT_STOP_WICK_ATR_BUFFER, entry * 0.0012, structure_buffer)
    wick_stop = recent_swing_high + wick_buffer
    raw_stop = max(entry + atr_stop_dist, wick_stop)
    max_stop = entry * (1 + SHORT_MAX_STOP_PCT / 100.0)
    stop = min(raw_stop, max_stop)

    if stop <= entry + min_stop_dist:
        stop = entry + min_stop_dist

    tp1 = entry * (1 - FIXED_TP1_PCT / 100.0)
    tp2 = entry * (1 - FIXED_TP2_PCT / 100.0)
    tp3 = entry * (1 - FIXED_TP3_PCT / 100.0)
    rr = (entry - tp1) / max(stop - entry, 1e-9)
    return stop, tp1, tp2, tp3, rr


def calculate_long_levels(entry: float, l1: List[float], last_atr1: float, last_atr5: float) -> Tuple[float, float, float, float, float]:
    if entry <= 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0

    recent_swing_low = min(l1[-12:]) if len(l1) >= 12 else min(l1) if l1 else entry
    min_stop_dist = entry * (LONG_MIN_STOP_PCT / 100.0)
    atr_stop_dist = max(last_atr1 * LONG_STOP_ATR_MULT, min_stop_dist)
    structure_buffer = recent_swing_low * (LONG_STRUCTURE_EXTRA_BUFFER_PCT / 100.0)
    wick_buffer = max(last_atr1 * LONG_STOP_WICK_ATR_BUFFER, entry * 0.0012, structure_buffer)
    wick_stop = recent_swing_low - wick_buffer
    raw_stop = min(entry - atr_stop_dist, wick_stop)
    max_stop = entry * (1 - LONG_MAX_STOP_PCT / 100.0)
    stop = max(raw_stop, max_stop)

    if stop >= entry - min_stop_dist:
        stop = entry - min_stop_dist

    tp1 = entry * (1 + FIXED_TP1_PCT / 100.0)
    tp2 = entry * (1 + FIXED_TP2_PCT / 100.0)
    tp3 = entry * (1 + FIXED_TP3_PCT / 100.0)
    rr = (tp1 - entry) / max(entry - stop, 1e-9)
    return stop, tp1, tp2, tp3, rr


# =========================================================
# ICT MOTORU
# =========================================================
def ict_find_pivots(hs: List[float], ls: List[float], left: int = 2, right: int = 2) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
    piv_h: List[Tuple[int, float]] = []
    piv_l: List[Tuple[int, float]] = []
    n = len(hs)
    if n < left + right + 3:
        return piv_h, piv_l
    for i in range(left, n - right):
        hh = hs[i]
        ll = ls[i]
        if all(hh >= hs[j] for j in range(i - left, i + right + 1) if j != i):
            if hh > max(hs[i-left:i] + hs[i+1:i+right+1]):
                piv_h.append((i, hh))
        if all(ll <= ls[j] for j in range(i - left, i + right + 1) if j != i):
            if ll < min(ls[i-left:i] + ls[i+1:i+right+1]):
                piv_l.append((i, ll))
    return piv_h, piv_l


def ict_detect_market_structure(k5: List[List[Any]], price: float) -> Dict[str, Any]:
    h5 = highs(k5)
    l5 = lows(k5)
    c5 = closes(k5)
    ph, pl = ict_find_pivots(h5, l5, max(1, ICT_PIVOT_LEFT), max(1, ICT_PIVOT_RIGHT))
    recent_ph = ph[-5:]
    recent_pl = pl[-5:]
    last_high = recent_ph[-1][1] if recent_ph else (max(h5[-20:-1]) if len(h5) > 20 else max(h5))
    prev_high = recent_ph[-2][1] if len(recent_ph) >= 2 else last_high
    last_low = recent_pl[-1][1] if recent_pl else (min(l5[-20:-1]) if len(l5) > 20 else min(l5))
    prev_low = recent_pl[-2][1] if len(recent_pl) >= 2 else last_low
    close_now = c5[-1]
    close_prev = c5[-2] if len(c5) >= 2 else close_now

    hh = last_high > prev_high
    lh = last_high < prev_high
    hl = last_low > prev_low
    ll = last_low < prev_low
    bias = "RANGE"
    if hh and hl:
        bias = "BULLISH"
    elif lh and ll:
        bias = "BEARISH"

    bos_up = close_now > last_high and close_prev <= last_high
    bos_down = close_now < last_low and close_prev >= last_low
    choch_up = bos_up and bias == "BEARISH"
    choch_down = bos_down and bias == "BULLISH"
    mss_up = close_now > max(h5[-8:-1]) if len(h5) >= 9 else False
    mss_down = close_now < min(l5[-8:-1]) if len(l5) >= 9 else False
    return {
        "structure_bias": bias,
        "hh": hh, "hl": hl, "lh": lh, "ll": ll,
        "last_structure_high": last_high,
        "prev_structure_high": prev_high,
        "last_structure_low": last_low,
        "prev_structure_low": prev_low,
        "bos_up": bos_up, "bos_down": bos_down,
        "choch_up": choch_up, "choch_down": choch_down,
        "mss_up": mss_up, "mss_down": mss_down,
        "pivot_high_count": len(ph),
        "pivot_low_count": len(pl),
    }


def ict_detect_equal_liquidity(k1: List[List[Any]], price: float) -> Dict[str, Any]:
    h1 = highs(k1)
    l1 = lows(k1)
    look = min(max(12, ICT_LIQUIDITY_LOOKBACK_1M), len(k1) - 2)
    hs = h1[-look-1:-1]
    ls = l1[-look-1:-1]
    tol = price * (ICT_EQUAL_LEVEL_TOLERANCE_PCT / 100.0)
    eq_high = False
    eq_low = False
    high_level = max(hs) if hs else price
    low_level = min(ls) if ls else price
    if hs:
        near_highs = [x for x in hs if abs(x - high_level) <= tol]
        eq_high = len(near_highs) >= 2
    if ls:
        near_lows = [x for x in ls if abs(x - low_level) <= tol]
        eq_low = len(near_lows) >= 2
    buyside_distance = pct_change(price, high_level) if price > 0 else 0.0
    sellside_distance = pct_change(price, low_level) if price > 0 else 0.0
    return {
        "equal_high": eq_high,
        "equal_low": eq_low,
        "buy_side_liquidity": high_level,
        "sell_side_liquidity": low_level,
        "buyside_distance_pct": round(buyside_distance, 2),
        "sellside_distance_pct": round(sellside_distance, 2),
    }


def ict_detect_fvg_zones(k1: List[List[Any]], price: float) -> Dict[str, Any]:
    if len(k1) < 5:
        return {"bullish_fvgs": [], "bearish_fvgs": [], "bullish_fvg_active": False, "bearish_fvg_active": False}
    look_start = max(2, len(k1) - max(8, ICT_FVG_LOOKBACK))
    bullish: List[Dict[str, Any]] = []
    bearish: List[Dict[str, Any]] = []
    for i in range(look_start, len(k1)):
        h2 = safe_float(k1[i-2][2]); l2 = safe_float(k1[i-2][3])
        hi = safe_float(k1[i][2]); li = safe_float(k1[i][3])
        if li > h2:
            low = h2; high = li
            mid = (low + high) / 2.0
            active = price >= low and price <= high * (1 + ICT_ZONE_TOLERANCE_PCT / 100.0)
            bullish.append({"low": low, "high": high, "mid": mid, "age": len(k1)-1-i, "active": active, "filled_pct": round(clamp((high - max(price, low)) / max(high - low, 1e-9) * 100, 0, 100), 1)})
        if hi < l2:
            low = hi; high = l2
            mid = (low + high) / 2.0
            active = price <= high and price >= low * (1 - ICT_ZONE_TOLERANCE_PCT / 100.0)
            bearish.append({"low": low, "high": high, "mid": mid, "age": len(k1)-1-i, "active": active, "filled_pct": round(clamp((min(price, high) - low) / max(high - low, 1e-9) * 100, 0, 100), 1)})
    bullish = sorted(bullish, key=lambda z: z["age"])[:4]
    bearish = sorted(bearish, key=lambda z: z["age"])[:4]
    return {
        "bullish_fvgs": bullish,
        "bearish_fvgs": bearish,
        "bullish_fvg_active": any(z.get("active") for z in bullish),
        "bearish_fvg_active": any(z.get("active") for z in bearish),
        "nearest_bullish_fvg": bullish[0] if bullish else {},
        "nearest_bearish_fvg": bearish[0] if bearish else {},
    }


def ict_detect_order_blocks(k1: List[List[Any]], price: float) -> Dict[str, Any]:
    if len(k1) < 20:
        return {"bullish_ob": {}, "bearish_ob": {}, "bullish_ob_near": False, "bearish_ob_near": False}
    atr1_vals = atr(k1, 14)
    last_atr = max(atr1_vals[-1], price * 0.0015)
    start = max(3, len(k1) - max(12, ICT_ORDER_BLOCK_LOOKBACK))
    bullish_ob: Dict[str, Any] = {}
    bearish_ob: Dict[str, Any] = {}
    for i in range(start, len(k1)):
        o = safe_float(k1[i][1]); h = safe_float(k1[i][2]); l = safe_float(k1[i][3]); c = safe_float(k1[i][4])
        body = abs(c - o)
        displacement = body >= last_atr * ICT_MIN_DISPLACEMENT_ATR
        if not displacement:
            continue
        if c > o:
            for j in range(i-1, max(start-1, i-8), -1):
                oj = safe_float(k1[j][1]); hj = safe_float(k1[j][2]); lj = safe_float(k1[j][3]); cj = safe_float(k1[j][4])
                if cj < oj:
                    bullish_ob = {"low": lj, "high": max(oj, cj), "full_high": hj, "index": j, "age": len(k1)-1-j}
                    break
        if c < o:
            for j in range(i-1, max(start-1, i-8), -1):
                oj = safe_float(k1[j][1]); hj = safe_float(k1[j][2]); lj = safe_float(k1[j][3]); cj = safe_float(k1[j][4])
                if cj > oj:
                    bearish_ob = {"low": min(oj, cj), "high": hj, "full_low": lj, "index": j, "age": len(k1)-1-j}
                    break
    bull_near = False
    bear_near = False
    if bullish_ob:
        bull_mid = (safe_float(bullish_ob.get("low")) + safe_float(bullish_ob.get("high"))) / 2
        bull_near = abs(pct_change(price, bull_mid)) <= ICT_MAX_OB_DISTANCE_PCT or (safe_float(bullish_ob.get("low")) <= price <= safe_float(bullish_ob.get("high")))
    if bearish_ob:
        bear_mid = (safe_float(bearish_ob.get("low")) + safe_float(bearish_ob.get("high"))) / 2
        bear_near = abs(pct_change(price, bear_mid)) <= ICT_MAX_OB_DISTANCE_PCT or (safe_float(bearish_ob.get("low")) <= price <= safe_float(bearish_ob.get("high")))
    return {"bullish_ob": bullish_ob, "bearish_ob": bearish_ob, "bullish_ob_near": bull_near, "bearish_ob_near": bear_near}


def ict_killzone_context() -> Dict[str, Any]:
    if not ICT_KILLZONE_ENABLED:
        return {"active": False, "name": "Kapalı", "score": 0.0}
    h = tr_now().hour
    london = ICT_LONDON_KILLZONE_START <= h < ICT_LONDON_KILLZONE_END
    ny = ICT_NY_KILLZONE_START <= h < ICT_NY_KILLZONE_END
    if london and ny:
        return {"active": True, "name": "Londra+NY overlap", "score": 1.5}
    if london:
        return {"active": True, "name": "Londra kill zone", "score": 1.0}
    if ny:
        return {"active": True, "name": "NY kill zone", "score": 1.2}
    return {"active": False, "name": "Kill zone dışı", "score": 0.0}


def build_ict_zone_context(k1: List[List[Any]], k5: List[List[Any]], k15: List[List[Any]], price: float) -> Dict[str, Any]:
    if not ICT_ENGINE_ENABLED or len(k1) < 50 or len(k5) < 50:
        return {"enabled": False, "reason": "ICT kapalı veya veri yetersiz."}

    c1 = closes(k1); h1 = highs(k1); l1 = lows(k1)
    c5 = closes(k5); h5 = highs(k5); l5 = lows(k5)
    look = min(max(20, ICT_SWING_LOOKBACK_5M), len(k5) - 2)
    seg_h = h5[-look:-1]
    seg_l = l5[-look:-1]
    if not seg_h or not seg_l:
        return {"enabled": False, "reason": "ICT swing verisi yok."}

    swing_high = max(seg_h)
    swing_low = min(seg_l)
    swing_range = max(swing_high - swing_low, 1e-9)
    range_pct = abs(pct_change(swing_low, swing_high)) if swing_low > 0 else 0.0
    equilibrium = swing_low + swing_range * 0.5
    discount_high = swing_high - swing_range * ICT_DISCOUNT_FIB_LOW
    discount_low = swing_high - swing_range * ICT_DISCOUNT_FIB_HIGH
    premium_low = swing_low + swing_range * (1.0 - ICT_PREMIUM_FIB_HIGH)
    premium_high = swing_low + swing_range * (1.0 - ICT_PREMIUM_FIB_LOW)
    tol = price * (ICT_ZONE_TOLERANCE_PCT / 100.0)

    in_discount_zone = discount_low - tol <= price <= discount_high + tol
    in_premium_zone = premium_low - tol <= price <= premium_high + tol or price >= equilibrium
    below_equilibrium = price < equilibrium
    above_equilibrium = price > equilibrium

    liq_look = min(max(8, ICT_LIQUIDITY_LOOKBACK_1M), len(k1) - 2)
    prev_low = min(l1[-liq_look-1:-1])
    prev_high = max(h1[-liq_look-1:-1])
    last_k = k1[-1]
    last_high = safe_float(last_k[2]); last_low = safe_float(last_k[3]); last_close = safe_float(last_k[4])
    upper_wick, lower_wick, body_ratio, red = candle_wick_ratios(last_k)
    sweep_low = last_low < prev_low * (1 - ICT_MIN_SWEEP_PCT / 100.0) and last_close > prev_low
    sweep_high = last_high > prev_high * (1 + ICT_MIN_SWEEP_PCT / 100.0) and last_close < prev_high

    structure = ict_detect_market_structure(k5, price)
    liquidity = ict_detect_equal_liquidity(k1, price)
    fvg = ict_detect_fvg_zones(k1, price)
    ob = ict_detect_order_blocks(k1, price)
    kill = ict_killzone_context()

    atr5_vals = atr(k5, 14)
    last_atr5 = max(atr5_vals[-1], price * 0.0015)
    bullish_displacement = False
    bearish_displacement = False
    for i in range(max(2, len(k1) - 8), len(k1)):
        ko = safe_float(k1[i][1]); kc = safe_float(k1[i][4])
        body = abs(kc - ko)
        if kc > ko and body >= max(last_atr5 * ICT_MIN_FVG_BODY_ATR, price * 0.0015):
            bullish_displacement = True
        if kc < ko and body >= max(last_atr5 * ICT_MIN_FVG_BODY_ATR, price * 0.0015):
            bearish_displacement = True

    recent_high_8 = max(h1[-9:-1])
    recent_low_8 = min(l1[-9:-1])
    e9_1 = ema(c1, 9)
    e21_1 = ema(c1, 21)
    choch_up_score = 0.0
    choch_down_score = 0.0
    choch_up_reasons: List[str] = []
    choch_down_reasons: List[str] = []

    if last_close > recent_high_8:
        choch_up_score += 2.0; choch_up_reasons.append("son mikro tepe üstü")
    if structure.get("choch_up") or structure.get("bos_up"):
        choch_up_score += 2.4; choch_up_reasons.append("BOS/CHOCH yukarı")
    if last_close > e9_1[-1]:
        choch_up_score += 1.3; choch_up_reasons.append("EMA9 üstü")
    if e9_1[-1] > e21_1[-1]:
        choch_up_score += 1.5; choch_up_reasons.append("EMA9/21 yukarı")
    if not red and lower_wick >= 0.22:
        choch_up_score += 1.0; choch_up_reasons.append("alt fitil alıcı savunması")
    if bullish_displacement:
        choch_up_score += 1.4; choch_up_reasons.append("bullish displacement")
    if fvg.get("bullish_fvg_active"):
        choch_up_score += 1.0; choch_up_reasons.append("bullish FVG aktif")
    if ob.get("bullish_ob_near"):
        choch_up_score += 1.0; choch_up_reasons.append("bullish OB yakın")

    if last_close < recent_low_8:
        choch_down_score += 2.0; choch_down_reasons.append("son mikro dip altı")
    if structure.get("choch_down") or structure.get("bos_down"):
        choch_down_score += 2.4; choch_down_reasons.append("BOS/CHOCH aşağı")
    if last_close < e9_1[-1]:
        choch_down_score += 1.3; choch_down_reasons.append("EMA9 altı")
    if e9_1[-1] < e21_1[-1]:
        choch_down_score += 1.5; choch_down_reasons.append("EMA9/21 aşağı")
    if red and upper_wick >= 0.18:
        choch_down_score += 1.0; choch_down_reasons.append("üst fitil satıcı reddi")
    if bearish_displacement:
        choch_down_score += 1.4; choch_down_reasons.append("bearish displacement")
    if fvg.get("bearish_fvg_active"):
        choch_down_score += 1.0; choch_down_reasons.append("bearish FVG aktif")
    if ob.get("bearish_ob_near"):
        choch_down_score += 1.0; choch_down_reasons.append("bearish OB yakın")

    short_pro_score = 0.0
    short_notes: List[str] = []
    if in_premium_zone or above_equilibrium:
        short_pro_score += 2.0; short_notes.append("premium/EQ üstü")
    if sweep_high:
        short_pro_score += 2.4; short_notes.append("üst likidite sweep")
    if liquidity.get("equal_high"):
        short_pro_score += 0.9; short_notes.append("equal high likiditesi")
    if choch_down_score >= ICT_MIN_CHOCH_SCORE:
        short_pro_score += 2.2; short_notes.append("CHOCH/BOS aşağı")
    if fvg.get("bearish_fvg_active") or bearish_displacement:
        short_pro_score += 1.5; short_notes.append("bearish FVG/displacement")
    if ob.get("bearish_ob_near"):
        short_pro_score += 1.2; short_notes.append("bearish OB/supply")
    if structure.get("structure_bias") == "BEARISH" or structure.get("mss_down"):
        short_pro_score += 1.0; short_notes.append("bearish yapı")
    if kill.get("active"):
        short_pro_score += safe_float(kill.get("score", 0)); short_notes.append(str(kill.get("name")))
    if in_discount_zone and sweep_low and choch_up_score >= choch_down_score:
        short_pro_score -= 2.5; short_notes.append("discount + alt sweep, short tehlikeli")

    long_pro_score = 0.0
    long_notes: List[str] = []
    if in_discount_zone or below_equilibrium:
        long_pro_score += 2.0; long_notes.append("discount/EQ altı")
    if sweep_low:
        long_pro_score += 2.4; long_notes.append("alt likidite sweep")
    if liquidity.get("equal_low"):
        long_pro_score += 0.9; long_notes.append("equal low likiditesi")
    if choch_up_score >= ICT_MIN_CHOCH_SCORE:
        long_pro_score += 2.2; long_notes.append("CHOCH/BOS yukarı")
    if fvg.get("bullish_fvg_active") or bullish_displacement:
        long_pro_score += 1.5; long_notes.append("bullish FVG/displacement")
    if ob.get("bullish_ob_near"):
        long_pro_score += 1.2; long_notes.append("bullish OB/demand")
    if structure.get("structure_bias") == "BULLISH" or structure.get("mss_up"):
        long_pro_score += 1.0; long_notes.append("bullish yapı")
    if kill.get("active"):
        long_pro_score += safe_float(kill.get("score", 0)); long_notes.append(str(kill.get("name")))
    if in_premium_zone and sweep_high and choch_down_score >= choch_up_score:
        long_pro_score -= 2.5; long_notes.append("premium + üst sweep, long tehlikeli")

    return {
        "enabled": True,
        "pro_enabled": bool(ICT_PRO_MODE_ENABLED),
        "swing_high": swing_high,
        "swing_low": swing_low,
        "range_pct": round(range_pct, 2),
        "equilibrium": equilibrium,
        "discount_low": discount_low,
        "discount_high": discount_high,
        "premium_low": premium_low,
        "premium_high": premium_high,
        "in_discount_zone": in_discount_zone,
        "in_premium_zone": in_premium_zone,
        "below_equilibrium": below_equilibrium,
        "above_equilibrium": above_equilibrium,
        "sweep_low": sweep_low,
        "sweep_high": sweep_high,
        "prev_low": prev_low,
        "prev_high": prev_high,
        "sell_side_liquidity_swept": sweep_low,
        "buy_side_liquidity_swept": sweep_high,
        "equal_high": liquidity.get("equal_high"),
        "equal_low": liquidity.get("equal_low"),
        "buy_side_liquidity": liquidity.get("buy_side_liquidity"),
        "sell_side_liquidity": liquidity.get("sell_side_liquidity"),
        "bullish_fvg": bool(fvg.get("bullish_fvg_active")),
        "bearish_fvg": bool(fvg.get("bearish_fvg_active")),
        "bullish_fvg_active": bool(fvg.get("bullish_fvg_active")),
        "bearish_fvg_active": bool(fvg.get("bearish_fvg_active")),
        "nearest_bullish_fvg": fvg.get("nearest_bullish_fvg", {}),
        "nearest_bearish_fvg": fvg.get("nearest_bearish_fvg", {}),
        "bullish_displacement": bullish_displacement,
        "bearish_displacement": bearish_displacement,
        "bullish_ob": ob.get("bullish_ob", {}),
        "bearish_ob": ob.get("bearish_ob", {}),
        "bullish_ob_near": ob.get("bullish_ob_near", False),
        "bearish_ob_near": ob.get("bearish_ob_near", False),
        "structure_bias": structure.get("structure_bias", "RANGE"),
        "bos_up": structure.get("bos_up", False),
        "bos_down": structure.get("bos_down", False),
        "choch_up": structure.get("choch_up", False),
        "choch_down": structure.get("choch_down", False),
        "mss_up": structure.get("mss_up", False),
        "mss_down": structure.get("mss_down", False),
        "last_structure_high": structure.get("last_structure_high", 0),
        "last_structure_low": structure.get("last_structure_low", 0),
        "choch_up_score": round(choch_up_score, 2),
        "choch_down_score": round(choch_down_score, 2),
        "choch_up_reason": " | ".join(choch_up_reasons[:8]) if choch_up_reasons else "CHOCH yukarı yok",
        "choch_down_reason": " | ".join(choch_down_reasons[:8]) if choch_down_reasons else "CHOCH aşağı yok",
        "last_upper_wick": round(upper_wick, 3),
        "last_lower_wick": round(lower_wick, 3),
        "last_red": red,
        "killzone_active": kill.get("active", False),
        "killzone_name": kill.get("name", "-"),
        "short_pro_score": round(short_pro_score, 2),
        "long_pro_score": round(long_pro_score, 2),
        "short_pro_reason": " | ".join(short_notes[:8]) if short_notes else "SHORT ICT bağlamı zayıf",
        "long_pro_reason": " | ".join(long_notes[:8]) if long_notes else "LONG ICT bağlamı zayıf",
        "reason": (
            f"ICT PRO Swing {fmt_num(swing_low)}→{fmt_num(swing_high)} | EQ {fmt_num(equilibrium)} | "
            f"Discount {fmt_num(discount_low)}-{fmt_num(discount_high)} | "
            f"Premium {fmt_num(premium_low)}-{fmt_num(premium_high)} | "
            f"Yapı {structure.get('structure_bias')} | SHORT ICT {short_pro_score:.1f} | LONG ICT {long_pro_score:.1f}"
        )
    }

def long_structure_confirmation(k1: List[List[Any]], k5: List[List[Any]], ict: Dict[str, Any]) -> Dict[str, Any]:
    if len(k1) < 30 or len(k5) < 30:
        return {"score": 0.0, "reason": "Long yapı verisi yetersiz"}
    c1 = closes(k1); h1 = highs(k1); l1 = lows(k1); c5 = closes(k5); v1 = volumes(k1)
    e9 = ema(c1, 9); e21 = ema(c1, 21); r1 = rsi(c1, 14)
    last_price = c1[-1]
    last_k = k1[-1]
    prev_k = k1[-2]
    recent_high_8 = max(h1[-9:-1])
    recent_low_8 = min(l1[-9:-1])
    score = 0.0
    reasons: List[str] = []
    upper, lower, body, red = candle_wick_ratios(last_k)

    if bool(ict.get("sweep_low")):
        score += 2.4; reasons.append("alt likidite süpürüldü")
    if bool(ict.get("in_discount_zone")):
        score += 2.0; reasons.append("0.5-0.618 discount/talep bölgesi")
    if lower >= 0.28 and not red:
        score += 1.8; reasons.append("alt fitil alıcı savunması")
    elif lower >= 0.38:
        score += 1.0; reasons.append("alt fitil savunma")
    if last_price > e9[-1]:
        score += 1.5; reasons.append("EMA9 üstü")
    if last_price > e21[-1]:
        score += 1.2; reasons.append("EMA21 üstü")
    if e9[-1] > e21[-1]:
        score += 1.4; reasons.append("EMA9/21 yukarı")
    if last_price > recent_high_8:
        score += 2.2; reasons.append("mikro tepe kırıldı")
    if safe_float(last_k[4]) > safe_float(last_k[1]) and safe_float(prev_k[4]) > safe_float(prev_k[1]):
        score += 1.2; reasons.append("arka arkaya alıcı mumu")
    if r1[-1] > r1[-2] and r1[-1] >= 45:
        score += 1.1; reasons.append("RSI toparlanıyor")
    if c5[-1] > c5[-2]:
        score += 1.2; reasons.append("5dk kapanış yukarı")
    vol_ratio = safe_float(v1[-1]) / max(avg(v1[-20:-1]), 1e-9)
    if safe_float(last_k[4]) > safe_float(last_k[1]) and vol_ratio >= 1.10:
        score += 1.2; reasons.append(f"alım hacmi x{vol_ratio:.2f}")
    if last_price < recent_low_8 and not ict.get("sweep_low"):
        score -= 2.0; reasons.append("dip kırılıyor, sweep teyidi yok")

    return {"score": round(score, 2), "reason": " | ".join(reasons[:8]) if reasons else "Net long dönüş yok"}


def long_close_confirmation_gate(k5: List[List[Any]], k15: List[List[Any]]) -> Dict[str, Any]:
    k5c = closed_klines(k5, "5m")
    k15c = closed_klines(k15, "15m")
    if len(k5c) < 30 or len(k15c) < 30:
        return {"passed": False, "class": "WAIT", "reason": "5m/15m kapanış verisi yetersiz."}
    c5v = closes(k5c); c15v = closes(k15c)
    e9_5 = ema(c5v, 9); e21_5 = ema(c5v, 21); e9_15 = ema(c15v, 9)
    k5_last = k5c[-1]; k15_last = k15c[-1]
    o5, cl5 = safe_float(k5_last[1]), safe_float(k5_last[4])
    o15, cl15 = safe_float(k15_last[1]), safe_float(k15_last[4])
    upper5, lower5, body5, red5 = candle_wick_ratios(k5_last)
    upper15, lower15, body15, red15 = candle_wick_ratios(k15_last)
    score5 = 0.0; reasons5: List[str] = []
    score15 = 0.0; reasons15: List[str] = []
    if cl5 > o5:
        score5 += 1.7; reasons5.append("5m yeşil kapandı")
    if cl5 > c5v[-2]:
        score5 += 1.2; reasons5.append("5m önceki kapanış üstü")
    if cl5 > e9_5[-1]:
        score5 += 1.3; reasons5.append("5m EMA9 üstü")
    if cl5 > e21_5[-1]:
        score5 += 1.1; reasons5.append("5m EMA21 üstü")
    if lower5 >= 0.25 and cl5 >= o5:
        score5 += 1.2; reasons5.append("5m alt fitil talep")
    if c5v[-1] > c5v[-2] > c5v[-3]:
        score5 += 0.9; reasons5.append("5m iki kapanış güçlü")
    if upper5 >= 0.45 and cl5 <= o5:
        score5 -= 1.5; reasons5.append("5m üst fitil satıcı")
    if cl5 < e9_5[-1] and red5:
        score5 -= 1.2; reasons5.append("5m hâlâ zayıf")
    if cl15 > o15:
        score15 += 1.2; reasons15.append("15m yeşil kapandı")
    if cl15 > c15v[-2]:
        score15 += 0.9; reasons15.append("15m önceki kapanış üstü")
    if cl15 > e9_15[-1]:
        score15 += 1.0; reasons15.append("15m EMA9 üstü")
    if lower15 >= 0.22 and cl15 >= o15:
        score15 += 0.8; reasons15.append("15m alt fitil talep")
    if upper15 >= 0.45 and red15:
        score15 -= 1.2; reasons15.append("15m üst fitil satıcı")
    pass5 = (not LONG_REQUIRE_5M_CONFIRM) or score5 >= LONG_MIN_5M_CONFIRM_SCORE
    pass15 = (not LONG_REQUIRE_15M_CONFIRM) or score15 >= LONG_MIN_15M_CONFIRM_SCORE
    passed = pass5 and pass15
    klass = "CLEAN" if score5 >= LONG_MIN_5M_CONFIRM_SCORE + 2 and score15 >= LONG_MIN_15M_CONFIRM_SCORE + 1 else "RISKY"
    if not passed:
        klass = "WAIT"
    return {
        "passed": passed, "class": klass,
        "score5": round(score5, 2), "score15": round(score15, 2),
        "reason": f"5m long skoru {score5:.1f}/{LONG_MIN_5M_CONFIRM_SCORE:.1f}: {'; '.join(reasons5[:4]) if reasons5 else 'net alıcı yok'} | 15m long skoru {score15:.1f}/{LONG_MIN_15M_CONFIRM_SCORE:.1f}: {'; '.join(reasons15[:4]) if reasons15 else 'ana onay yok'}"
    }


def interval_to_milliseconds(interval: str) -> int:
    mp = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1H": 3_600_000, "1h": 3_600_000, "4H": 14_400_000, "4h": 14_400_000}
    return mp.get(interval, 60_000)


def kline_start_ms(kline: List[Any]) -> int:
    ts = safe_float(kline[0], 0)
    if ts <= 0:
        return 0
    return int(ts if ts > 10_000_000_000 else ts * 1000)


def is_kline_closed(kline: List[Any], interval: str, now_ms: Optional[int] = None) -> bool:
    start_ms = kline_start_ms(kline)
    if start_ms <= 0:
        return True
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    return now_ms >= start_ms + interval_to_milliseconds(interval)


def closed_klines(klines: List[List[Any]], interval: str) -> List[List[Any]]:
    if not klines:
        return []
    now_ms = int(time.time() * 1000)
    if is_kline_closed(klines[-1], interval, now_ms):
        return klines
    return klines[:-1]


def short_close_confirmation_gate(k5: List[List[Any]], k15: List[List[Any]], res: Dict[str, Any]) -> Dict[str, Any]:
    if not CLOSE_CONFIRM_GATE_ENABLED:
        return {"passed": True, "class": "CLEAN", "reason": "Kapanış kapısı kapalı."}

    k5c = closed_klines(k5, "5m")
    k15c = closed_klines(k15, "15m")
    if len(k5c) < 30 or len(k15c) < 30:
        return {"passed": False, "class": "WAIT", "reason": "5m/15m kapanış verisi yetersiz; 1m radar takipte."}

    c5v = closes(k5c)
    c15v = closes(k15c)
    e9_5 = ema(c5v, 9)
    e21_5 = ema(c5v, 21)
    e9_15 = ema(c15v, 9)
    r5 = rsi(c5v, 14)
    r15 = rsi(c15v, 14)

    k5_last = k5c[-1]
    k15_last = k15c[-1]
    o5, h5, l5, cl5 = safe_float(k5_last[1]), safe_float(k5_last[2]), safe_float(k5_last[3]), safe_float(k5_last[4])
    o15, h15, l15, cl15 = safe_float(k15_last[1]), safe_float(k15_last[2]), safe_float(k15_last[3]), safe_float(k15_last[4])
    upper5, lower5, body5, red5 = candle_wick_ratios(k5_last)
    upper15, lower15, body15, red15 = candle_wick_ratios(k15_last)

    score5 = 0.0; reasons5: List[str] = []
    if red5:
        score5 += 1.8; reasons5.append("5m kırmızı kapandı")
    if cl5 < c5v[-2]:
        score5 += 1.1; reasons5.append("5m önceki kapanış altı")
    if cl5 < e9_5[-1]:
        score5 += 1.4; reasons5.append("5m EMA9 altı")
    if cl5 < e21_5[-1]:
        score5 += 1.3; reasons5.append("5m EMA21 altı")
    if upper5 >= 0.22 and cl5 <= o5:
        score5 += 1.0; reasons5.append("5m üst fitil/red")
    if c5v[-1] < c5v[-2] < c5v[-3]:
        score5 += 1.0; reasons5.append("5m iki kapanış zayıf")
    if lower5 >= 0.45 and cl5 >= o5:
        score5 -= 1.4; reasons5.append("5m alt fitil alıcı savunması")
    if cl5 > e9_5[-1] and not red5:
        score5 -= 1.2; reasons5.append("5m kapanış hâlâ diri")

    score15 = 0.0; reasons15: List[str] = []
    if red15:
        score15 += 1.4; reasons15.append("15m kırmızı kapandı")
    if cl15 < c15v[-2]:
        score15 += 1.0; reasons15.append("15m önceki kapanış altı")
    if cl15 < e9_15[-1]:
        score15 += 1.4; reasons15.append("15m EMA9 altı")
    if upper15 >= 0.20 and cl15 <= o15:
        score15 += 0.9; reasons15.append("15m üst fitil/red")
    if r15[-1] >= 62:
        score15 += 0.8; reasons15.append(f"15m şişkin RSI {r15[-1]:.1f}")
    if lower15 >= 0.45 and cl15 >= o15:
        score15 -= 1.2; reasons15.append("15m alt fitil alıcı savunması")
    if cl15 > e9_15[-1] and cl15 > c15v[-2] and not red15:
        score15 -= 1.6; reasons15.append("15m kapanış hâlâ yukarı")

    pass5 = (not CLOSE_CONFIRM_REQUIRE_5M) or score5 >= CLOSE_CONFIRM_MIN_5M_SCORE
    pass15 = (not CLOSE_CONFIRM_REQUIRE_15M) or score15 >= CLOSE_CONFIRM_MIN_15M_SCORE
    passed = pass5 and pass15
    clean = score5 >= CLOSE_CONFIRM_CLEAN_5M_SCORE and score15 >= CLOSE_CONFIRM_CLEAN_15M_SCORE
    decision_class = "CLEAN" if clean else "RISKY"
    if not passed:
        decision_class = "WAIT"
    reason = (
        f"5m kapanış skoru {score5:.1f}/{CLOSE_CONFIRM_MIN_5M_SCORE:.1f}: "
        f"{'; '.join(reasons5[:4]) if reasons5 else 'net zayıflama yok'} | "
        f"15m kapanış skoru {score15:.1f}/{CLOSE_CONFIRM_MIN_15M_SCORE:.1f}: "
        f"{'; '.join(reasons15[:4]) if reasons15 else 'net onay yok'}"
    )
    return {"passed": passed, "class": decision_class, "score5": round(score5, 2), "score15": round(score15, 2), "reason": reason}


def final_quality_gate(res: Dict[str, Any]) -> Tuple[bool, str, float]:
    score = 0.0
    hard_blocks: List[str] = []
    soft_notes: List[str] = []

    inv = res.get("invisible_face") if isinstance(res.get("invisible_face"), dict) else {}
    breakdown = safe_float(res.get("breakdown_score", 0))
    trend_guard_score = safe_float(res.get("trend_guard_score", 0))
    rr = safe_float(res.get("rr", 0))
    is_risky_scalp = str(res.get("signal_label", "")) == "RİSKLİ TP1 SCALP"
    is_tepe_early = bool(res.get("top_early_short")) or bool(inv.get("top_early_short")) or str(res.get("signal_label", "")) == "TEPE ERKEN SHORT"
    min_rr_required = RISKY_SCALP_MIN_RR_TP1 if is_risky_scalp or is_tepe_early else MIN_RR_TP1
    verify = safe_float(res.get("verify_score", 0))
    red_count = int(safe_float(res.get("red_count_5", 0)))
    green_streak = int(safe_float(res.get("green_streak", 0)))
    rsi1_val = safe_float(res.get("rsi1", 50))
    rsi5_val = safe_float(res.get("rsi5", 50))
    pump20 = safe_float(res.get("pump_20m", 0))
    drop_from_peak = safe_float(inv.get("drop_from_peak_pct", 0))
    bounce_from_low = safe_float(inv.get("bounce_from_low_pct", 0))
    top_exit_score = safe_float(inv.get("top_exit_score", 0))

    # V6: Whale Eye skorunu kalite kapısına ekle
    whale_eye = res.get("whale_eye", {})
    whale_score = safe_float(whale_eye.get("total_score", 0))
    whale_confidence = str(whale_eye.get("whale_confidence", "DÜŞÜK"))

    if drop_from_peak >= TEPE_ERKEN_TOO_LATE_DROP:
        hard_blocks.append(f"düşüş kaçmış/tepe uzak %{drop_from_peak:.2f}")
        stats["tepe_late_block"] += 1
    if drop_from_peak > 1.0 and bounce_from_low <= TEPE_ERKEN_BLOCK_LOCAL_LOW_BOUNCE:
        hard_blocks.append(f"yerel dibe yakın; düşüş sonu short riski, bounce %{bounce_from_low:.2f}")
        stats["tepe_late_block"] += 1

    if rr >= min_rr_required:
        score += 1.2
    else:
        hard_blocks.append(f"RR zayıf {rr:.2f}/{min_rr_required:.2f}")

    if breakdown >= TREND_BREAKDOWN_MIN_SCORE:
        score += 1.8
    elif is_tepe_early and top_exit_score >= TEPE_ERKEN_MIN_EXIT_SCORE:
        score += 1.4
        soft_notes.append(f"tam kırılım beklenmedi; tepe para çıkışı erken skor {top_exit_score:.1f}")
    elif trend_guard_score >= TREND_GUARD_SCORE_BLOCK or green_streak >= 3:
        hard_blocks.append(f"trend var ama kırılım zayıf {breakdown:.1f}/{TREND_BREAKDOWN_MIN_SCORE:.1f}")
    else:
        score += 0.5
        soft_notes.append(f"kırılım sınırda {breakdown:.1f}")

    # V6: Whale Eye bonus/malus
    if whale_confidence == "ÇOK_YÜKSEK":
        score += 2.5
        soft_notes.append(f"🐋 Whale Eye ÇOK YÜKSEK güven: {whale_score:.1f}")
    elif whale_confidence == "YÜKSEK":
        score += 1.5
        soft_notes.append(f"🐋 Whale Eye YÜKSEK güven: {whale_score:.1f}")
    elif whale_confidence == "ORTA":
        score += 0.5
        soft_notes.append(f"🐋 Whale Eye ORTA güven: {whale_score:.1f}")
    elif whale_score < -5:
        score -= 2.0
        hard_blocks.append(f"🐋 Whale Eye balina karşıtı sinyal: {whale_score:.1f}")

    if verify >= MIN_VERIFY_SCORE_FOR_SIGNAL:
        score += 1.4
    elif is_tepe_early and top_exit_score >= TEPE_ERKEN_MIN_EXIT_SCORE:
        score += 0.7
    else:
        soft_notes.append(f"doğrulama düşük {verify:.1f}")

    passed = score >= MIN_QUALITY_SCORE and not hard_blocks
    reason_parts = hard_blocks if hard_blocks else soft_notes
    return passed, " | ".join(reason_parts[:6]) if reason_parts else "Para koruma kapısı temiz", round(score, 2)


# =========================================================
# ANA ANALİZ FONKSİYONU (WHALE EYE ENTEGRASYONLU)
# =========================================================

async def analyze_symbol(symbol: str, tickers24: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    symbol = normalize_symbol(symbol)

    if is_blocked_coin_symbol(symbol):
        stats["blocked_coin_skip"] += 1
        return None

    if okx_live_symbols and symbol not in okx_live_symbols:
        stats["invalid_symbol_skip"] += 1
        return None

    if symbol_temporarily_blocked(symbol):
        stats["blocked_symbol_skip"] += 1
        return None

    if tickers24 and symbol not in tickers24:
        stats["invalid_symbol_skip"] += 1
        return None

    k1 = await get_klines(symbol, "1m", 120)
    k5 = await get_klines(symbol, "5m", 120)
    k15 = await get_klines(symbol, "15m", 120)

    if len(k1) < 50 or len(k5) < 50 or len(k15) < 50:
        stats["no_data"] += 1
        return None

    c1 = closes(k1); c5 = closes(k5); c15 = closes(k15)
    h1 = highs(k1); l1 = lows(k1); v1 = volumes(k1); v5 = volumes(k5)

    ema9_1 = ema(c1, 9); ema21_1 = ema(c1, 21); ema50_5 = ema(c5, 50)
    ema_fast_15 = ema(c15, SHORT_15M_FAST_MA); ema_slow_15 = ema(c15, SHORT_15M_SLOW_MA)
    rsi1 = rsi(c1, 14); rsi5 = rsi(c5, 14); rsi15 = rsi(c15, 14)
    atr1 = atr(k1, 14); atr5 = atr(k5, 14)

    last_price = c1[-1]; prev_price = c1[-2]
    last_rsi1 = rsi1[-1]; prev_rsi1 = rsi1[-2]
    last_rsi5 = rsi5[-1]; last_rsi15 = rsi15[-1]
    last_ema9_1 = ema9_1[-1]; last_ema21_1 = ema21_1[-1]; last_ema50_5 = ema50_5[-1]
    last_ma_fast_15 = ema_fast_15[-1] if ema_fast_15 else 0.0
    last_ma_slow_15 = ema_slow_15[-1] if ema_slow_15 else 0.0
    last_atr1 = max(atr1[-1], last_price * 0.0014)
    last_atr5 = max(atr5[-1], last_price * 0.0019)

    t24 = tickers24.get(symbol, {})
    last_px_24 = safe_float(t24.get("last", 0)) or last_price
    vol24h = safe_float(t24.get("vol24h", 0))
    vol_ccy_24h = safe_float(t24.get("volCcy24h", 0))
    quote_vol = max(vol_ccy_24h, vol24h * max(last_px_24, 1e-9))
    if quote_vol < MIN_24H_QUOTE_VOLUME:
        stats["volume_reject"] += 1
        return None

    pump_10m = pct_change(min(c1[-11:-1]), last_price) if len(c1) >= 12 else pct_change(min(c1[:-1]), last_price)
    pump_20m = pct_change(min(c1[-21:-1]), last_price) if len(c1) >= 22 else pct_change(min(c1[:-1]), last_price)
    pump_1h = pct_change(min(c5[-13:-1]), last_price) if len(c5) >= 14 else pct_change(min(c5[:-1]), last_price)
    dist_from_ema21 = pct_change(last_ema21_1, last_price)
    vol_ratio_1m = safe_float(v1[-1]) / max(avg(v1[-20:-1]), 1e-9)
    vol_ratio_5m = safe_float(v5[-1]) / max(avg(v5[-12:-1]), 1e-9)

    recent_high_20 = max(h1[-21:-1])
    last_kline = k1[-1]; prev_kline = k1[-2]
    rej_score = candle_rejection_score(last_kline)

    failed_breakout = safe_float(last_kline[2]) > recent_high_20 and last_price < recent_high_20
    micro_bear = last_price < prev_price and last_price < last_ema9_1
    bear_cross = last_ema9_1 < last_ema21_1 and ema9_1[-2] >= ema21_1[-2]
    losing_momentum = last_rsi1 < prev_rsi1 and last_rsi1 < 60
    weak_close = last_price <= safe_float(prev_kline[3]) or last_price < safe_float(last_kline[1])
    structure_turn = lower_highs(h1, 3) and lower_lows(l1, 3)
    red_count_5 = recent_red_count(k1, 5)
    green_streak = consecutive_green_count(k1, 6)

    breakdown = short_breakdown_confirmation(k1, k5)
    breakdown_score = safe_float(breakdown.get("score", 0))
    ict_context = build_ict_zone_context(k1, k5, k15, last_price)

    # =========================================================
    # V6 WHALE EYE - BURADA ÇAĞIRILIYOR
    # =========================================================
    price_change_5m = pct_change(c5[-2], last_price) if len(c5) >= 2 else 0.0
    whale_eye = await build_full_whale_eye_analysis(symbol, last_price, price_change_5m, k1, "SHORT")
    # =========================================================

    trend_guard = trend_continuation_guard(
        pump_10m=pump_10m, pump_20m=pump_20m, last_price=last_price,
        ema9=last_ema9_1, ema21=last_ema21_1, rsi1_val=last_rsi1, rsi5_val=last_rsi5,
        rej_score=rej_score, weak_close=weak_close, structure_turn=structure_turn,
        breakdown_score=breakdown_score, red_count=red_count_5,
    )

    strong_breakout_continue = (
        pump_20m > 2.8 and last_price > last_ema9_1 > last_ema21_1 and
        last_rsi1 > 66 and last_rsi5 > 66 and rej_score < 10 and
        not weak_close and not structure_turn and breakdown_score < TREND_BREAKDOWN_MIN_SCORE
    )

    candidate_score = 0.0; ready_score = 0.0; verify_score = 0.0
    reasons: List[str] = []

    if pump_10m >= 0.8:
        candidate_score += 9; reasons.append(f"10dk pump %{pump_10m:.2f}")
    if pump_20m >= 1.35:
        candidate_score += 11; reasons.append(f"20dk pump %{pump_20m:.2f}")
    if pump_1h >= 2.5:
        candidate_score += 10; reasons.append(f"1s pump %{pump_1h:.2f}")
    if last_rsi5 >= 64:
        candidate_score += 9; reasons.append(f"5dk RSI {last_rsi5:.1f}")
    if dist_from_ema21 >= 0.55:
        candidate_score += 9; reasons.append(f"EMA21 üstü %{dist_from_ema21:.2f}")
    if vol_ratio_1m >= 1.45:
        candidate_score += 8; reasons.append(f"1dk hacim x{vol_ratio_1m:.2f}")
    if vol_ratio_5m >= 1.25:
        candidate_score += 6; reasons.append(f"5dk hacim x{vol_ratio_5m:.2f}")

    if rej_score >= 10:
        ready_score += clamp(rej_score, 0, 18); reasons.append(f"İğne/red {rej_score:.1f}")
    if failed_breakout:
        ready_score += 13; reasons.append("Sahte kırılım")
    if micro_bear:
        ready_score += 9; reasons.append("1dk zayıf kapanış")
    if bear_cross:
        ready_score += 9; reasons.append("EMA9/21 kısa zayıflama")
    if losing_momentum:
        ready_score += 7; reasons.append("RSI momentum düşüşü")
    if structure_turn:
        ready_score += 10; reasons.append("Alt yapı bozuluyor")

    if last_price < last_ema9_1:
        verify_score += 10; reasons.append("Fiyat EMA9 altı")
    if last_price < last_ema21_1:
        verify_score += 8; reasons.append("Fiyat EMA21 altı")
    if last_rsi1 < 50:
        verify_score += 8; reasons.append("1dk RSI 50 altı")
    elif last_rsi1 < 54:
        verify_score += 4; reasons.append("1dk RSI gevşiyor")
    if weak_close:
        verify_score += 8; reasons.append("Zayıf son mum")
    if c5[-1] < c5[-2] and c5[-1] < c5[-3]:
        verify_score += 8; reasons.append("5dk gevşeme")
    if last_rsi15 >= 56:
        verify_score += 5; reasons.append("15dk hâlâ şişkin")
    if last_price > last_ema50_5:
        verify_score += 4; reasons.append("5dk EMA50 üstünde, dönüş alanı var")
    if breakdown_score >= TREND_BREAKDOWN_MIN_SCORE:
        verify_score += 9; stats["trend_breakdown_pass"] += 1
        reasons.append(f"Short kırılım teyidi {breakdown_score:.1f}: {breakdown.get('reason', '')}")
    elif breakdown_score >= TREND_BREAKDOWN_MIN_SCORE * 0.65:
        verify_score += 3
        reasons.append(f"Kırılım yarım {breakdown_score:.1f}: {breakdown.get('reason', '')}")

    # V6: Whale Eye skorunu ekle
    whale_score = safe_float(whale_eye.get("total_score", 0))
    whale_confidence = str(whale_eye.get("whale_confidence", "DÜŞÜK"))
    if whale_score > 0:
        reasons.append(f"🐋 Whale Eye: +{whale_score:.1f} ({whale_confidence})")
        if whale_confidence == "ÇOK_YÜKSEK":
            candidate_score += whale_score * 0.7
            ready_score += whale_score * 0.5
            verify_score += whale_score * 0.5
        elif whale_confidence == "YÜKSEK":
            candidate_score += whale_score * 0.5
            ready_score += whale_score * 0.4
            verify_score += whale_score * 0.3
        else:
            candidate_score += whale_score * 0.3
            ready_score += whale_score * 0.2
    elif whale_score < 0:
        reasons.append(f"🐋 Whale Eye uyarı: {whale_score:.1f}")
        candidate_score += whale_score * 0.5
        verify_score += whale_score * 0.3

    if SHORT_ICT_CONTEXT_ENABLED and isinstance(ict_context, dict) and ict_context.get("enabled"):
        short_ict_score = safe_float(ict_context.get("short_pro_score", 0))
        if short_ict_score >= ICT_SHORT_MIN_PRO_SCORE:
            candidate_score += 6; ready_score += 5; verify_score += 4
            reasons.append(f"ICT PRO SHORT onayı {short_ict_score:.1f}")
        if ict_context.get("in_premium_zone") or ict_context.get("above_equilibrium"):
            candidate_score += 2
        if ict_context.get("sweep_high"):
            ready_score += 4; reasons.append("ICT üst likidite süpürme")
        if ict_context.get("choch_down") or ict_context.get("bos_down") or ict_context.get("mss_down"):
            verify_score += 4; reasons.append("ICT BOS/CHOCH/MSS aşağı")

    candidate_score = max(candidate_score, 0.0)
    ready_score = max(ready_score, 0.0)
    verify_score = max(verify_score, 0.0)
    total_score = candidate_score + ready_score + verify_score

    entry = last_price
    stop, tp1, tp2, tp3, rr = calculate_short_levels(entry, h1, last_atr1, last_atr5)

    # V6: Whale Eye güçlüyse sinyal eşiğini düşür
    effective_min_signal = MIN_SIGNAL_SCORE
    effective_min_ready = MIN_READY_SCORE
    if whale_confidence == "ÇOK_YÜKSEK":
        effective_min_signal = max(40, MIN_SIGNAL_SCORE - 15)
        effective_min_ready = max(30, MIN_READY_SCORE - 10)
    elif whale_confidence == "YÜKSEK":
        effective_min_signal = max(48, MIN_SIGNAL_SCORE - 10)
        effective_min_ready = max(35, MIN_READY_SCORE - 6)

    if candidate_score < MIN_CANDIDATE_SCORE:
        stage = "IGNORE"
        stats["weak_candidate_reject"] += 1
    elif (candidate_score + ready_score) < effective_min_ready:
        stage = "HOT"
        stats["hot_add"] += 1
    elif total_score < effective_min_signal:
        stage = "READY"
        stats["weak_signal_reject"] += 1
    else:
        stage = "SIGNAL"

    if stage == "SIGNAL" and rr < MIN_RR_TP1:
        stage = "READY"
        total_score -= 6
        stats["rr_block"] += 1
        reasons.append(f"RR zayıf {rr:.2f}")

    final_payload = {
        "symbol": symbol,
        "stage": stage,
        "score": round(total_score, 2),
        "candidate_score": round(candidate_score, 2),
        "ready_score": round(ready_score, 2),
        "verify_score": round(verify_score, 2),
        "price": entry,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rr": round(rr, 2),
        "pump_10m": round(pump_10m, 2),
        "pump_20m": round(pump_20m, 2),
        "pump_1h": round(pump_1h, 2),
        "rsi1": round(last_rsi1, 2),
        "rsi5": round(last_rsi5, 2),
        "rsi15": round(last_rsi15, 2),
        "ma_fast_15m": round(last_ma_fast_15, 8),
        "ma_slow_15m": round(last_ma_slow_15, 8),
        "ma15_gate_pass": bool(last_ma_fast_15 > 0 and last_ma_slow_15 > 0 and last_ma_fast_15 < last_ma_slow_15),
        "vol_ratio_1m": round(vol_ratio_1m, 2),
        "vol_ratio_5m": round(vol_ratio_5m, 2),
        "quote_volume": quote_vol,
        "trend_guard_score": safe_float(trend_guard.get("score", 0)),
        "breakdown_score": breakdown_score,
        "green_streak": green_streak,
        "red_count_5": red_count_5,
        "quality_score": 0.0,
        "quality_reason": "-",
        "reason": " | ".join(reasons[:15]) if reasons else "Sebep yok",
        "ict": ict_context,
        "whale_eye": whale_eye,  # V6 YENI
    }

    if (strong_breakout_continue or trend_guard.get("blocked")) and whale_confidence not in ("ÇOK_YÜKSEK", "YÜKSEK"):
        stats["trend_strong_reject"] += 1
        stats["trend_guard_block_signal"] += 1
        final_payload["stage"] = "HOT"
        final_payload["score"] = round(max(total_score, MIN_CANDIDATE_SCORE), 2)
        final_payload["reason"] = f"TREND DEVAM KORUMASI: {trend_guard.get('reason', '')} | {final_payload['reason']}"[:900]
        return final_payload

    if final_payload["stage"] == "SIGNAL":
        close_gate = short_close_confirmation_gate(k5, k15, final_payload)
        final_payload["close_confirm_gate"] = close_gate
        final_payload["reason"] = f"{final_payload.get('reason', '')} | 5m/15m: {close_gate.get('reason', '-')}"[:1400]
        if not close_gate.get("passed", False):
            final_payload["stage"] = "READY"
            final_payload["score"] = round(safe_float(final_payload.get("score", 0)) - 6, 2)
            stats["close_confirm_block"] += 1
            return final_payload

    if final_payload["stage"] == "SIGNAL":
        passed, q_reason, q_score = final_quality_gate(final_payload)
        final_payload["quality_score"] = q_score
        final_payload["quality_reason"] = q_reason
        if not passed:
            final_payload["stage"] = "READY"
            final_payload["score"] = round(safe_float(final_payload["score"]) - 7, 2)
            stats["quality_gate_block"] += 1
            final_payload["reason"] = f"{final_payload['reason']} | Kalite kapısı: {q_reason}"

    final_payload = enforce_single_short_al_rules(final_payload)
    return final_payload



async def analyze_long_symbol(symbol: str, tickers24: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not LONG_ENGINE_ENABLED:
        return None

    symbol = normalize_symbol(symbol)
    if is_blocked_coin_symbol(symbol):
        return None
    if okx_live_symbols and symbol not in okx_live_symbols:
        return None
    if symbol_temporarily_blocked(symbol):
        return None
    if tickers24 and symbol not in tickers24:
        return None

    k1 = await get_klines(symbol, "1m", 120)
    k5 = await get_klines(symbol, "5m", 120)
    k15 = await get_klines(symbol, "15m", 120)
    if len(k1) < 60 or len(k5) < 60 or len(k15) < 50:
        return None

    c1 = closes(k1); h1 = highs(k1); l1 = lows(k1); v1 = volumes(k1)
    c5 = closes(k5); v5 = volumes(k5); c15 = closes(k15)
    ema9_1 = ema(c1, 9); ema21_1 = ema(c1, 21)
    ema50_5 = ema(c5, 50)
    rsi1 = rsi(c1, 14); rsi5 = rsi(c5, 14); rsi15 = rsi(c15, 14)
    atr1 = atr(k1, 14); atr5 = atr(k5, 14)

    last_price = c1[-1]
    last_rsi1 = rsi1[-1]; prev_rsi1 = rsi1[-2]
    last_rsi5 = rsi5[-1]; last_rsi15 = rsi15[-1]
    last_atr1 = max(atr1[-1], last_price * 0.0014)

    t24 = tickers24.get(symbol, {})
    last_px_24 = safe_float(t24.get("last", 0)) or last_price
    vol24h = safe_float(t24.get("vol24h", 0))
    vol_ccy_24h = safe_float(t24.get("volCcy24h", 0))
    quote_vol = max(vol_ccy_24h, vol24h * max(last_px_24, 1e-9))
    if quote_vol < MIN_24H_QUOTE_VOLUME:
        return None

    ict = build_ict_zone_context(k1, k5, k15, last_price)
    if not ict.get("enabled") or safe_float(ict.get("range_pct", 0)) < ICT_MIN_RANGE_PCT:
        return None

    drop_20m = max(0.0, abs(pct_change(max(c1[-21:-1]), last_price))) if len(c1) >= 22 and last_price < max(c1[-21:-1]) else 0.0
    drop_1h = max(0.0, abs(pct_change(max(c5[-13:-1]), last_price))) if len(c5) >= 14 and last_price < max(c5[-13:-1]) else 0.0
    drop_10m = max(0.0, abs(pct_change(max(c1[-11:-1]), last_price))) if len(c1) >= 12 and last_price < max(c1[-11:-1]) else 0.0
    bounce_from_low = pct_change(min(l1[-20:]), last_price) if len(l1) >= 20 and min(l1[-20:]) > 0 else 0.0
    vol_ratio_1m = safe_float(v1[-1]) / max(avg(v1[-20:-1]), 1e-9)
    vol_ratio_5m = safe_float(v5[-1]) / max(avg(v5[-12:-1]), 1e-9)
    upper_wick, lower_wick, body_ratio, red = candle_wick_ratios(k1[-1])
    green = not red

    whale_eye = await build_full_whale_eye_analysis(symbol, last_price, -drop_10m, k1, "LONG")

    book = await get_okx_orderbook(symbol)
    trades = await get_okx_recent_trades(symbol, 120)
    flow = analyze_trade_flow(trades)

    buy_to_sell = safe_float(flow.get("buy_to_sell", 0))
    sell_to_buy = safe_float(flow.get("sell_to_buy", 0))
    book_pressure = safe_float(book.get("book_pressure", 0))
    bid_wall_added = bool(book.get("bid_wall_added", False))
    ask_wall_pulled = bool(book.get("ask_wall_pulled", False))
    bid_defense = bool(book.get("ok")) and (bid_wall_added or ask_wall_pulled or book_pressure <= -0.12)
    buyer_defense = lower_wick >= 0.28 or buy_to_sell >= LONG_MIN_BUY_TO_SELL or bid_defense or (green and vol_ratio_1m >= 0.85)

    structure = long_structure_confirmation(k1, k5, ict)
    structure_score = safe_float(structure.get("score", 0))
    close_gate = long_close_confirmation_gate(k5, k15)

    true_structure_up = bool(ict.get("bos_up") or ict.get("choch_up") or ict.get("mss_up"))
    ema9_15 = ema(c15, 9)
    ema21_15 = ema(c15, 21)
    price_below_15m_fast = bool(ema9_15 and ema21_15 and last_price < ema9_15[-1] and last_price < ema21_15[-1])
    bearish_context = str(ict.get("structure_bias", "")).upper() == "BEARISH" and not true_structure_up
    seller_flow_dominant = sell_to_buy >= LONG_SELL_TO_BUY_HARD_BLOCK and buy_to_sell < LONG_MIN_BUY_TO_SELL
    weak_live_volume = vol_ratio_1m <= LONG_WEAK_VOL_1M_BLOCK and vol_ratio_5m <= LONG_WEAK_VOL_5M_BLOCK
    mixed_bearish_zone = bool(ict.get("bearish_fvg_active") or ict.get("bearish_ob_near"))
    long_hard_blocks: List[str] = []
    if LONG_BEARISH_CONTEXT_HARD_BLOCK_ENABLED:
        if bearish_context and seller_flow_dominant and (weak_live_volume or price_below_15m_fast or mixed_bearish_zone):
            long_hard_blocks.append(
                f"LONG yasak: BEARISH yapı + gerçek BOS/CHOCH/MSS↑ yok + satıcı akışı x{sell_to_buy:.2f}; "
                f"hacim 1m/5m x{vol_ratio_1m:.2f}/x{vol_ratio_5m:.2f}"
            )
        if LONG_REQUIRE_TRUE_STRUCTURE_UP and bearish_context and not ict.get("sweep_low") and safe_float(ict.get("short_pro_score", 0)) >= safe_float(ict.get("long_pro_score", 0)) - 1.0:
            long_hard_blocks.append(
                f"LONG yasak: yapı BEARISH, sweep alt yok, SHORT ICT {safe_float(ict.get('short_pro_score', 0)):.1f} LONG ICT'ye yakın"
            )

    candidate_score = 0.0; ready_score = 0.0; verify_score = 0.0
    reasons: List[str] = []

    if drop_20m >= LONG_MIN_DROP_20M:
        candidate_score += 7; reasons.append(f"20dk düşüş %{drop_20m:.2f}")
    if drop_1h >= LONG_MIN_DROP_1H:
        candidate_score += 8; reasons.append(f"1s düşüş %{drop_1h:.2f}")
    if ict.get("in_discount_zone"):
        candidate_score += 12; reasons.append("ICT discount bölgesi")
    if ict.get("sweep_low"):
        ready_score += 14; reasons.append("Alt likidite süpürüldü")
    if lower_wick >= 0.28:
        ready_score += 9; reasons.append(f"Alt fitil {lower_wick:.2f}")
    if buyer_defense:
        ready_score += 8; reasons.append("Alıcı savunması")
    if buy_to_sell >= LONG_MIN_BUY_TO_SELL:
        ready_score += 8; reasons.append(f"Alış baskın x{buy_to_sell:.2f}")
    if bid_defense:
        ready_score += 7; reasons.append("Orderbook bid savunması")
    if safe_float(ict.get("long_pro_score", 0)) >= ICT_LONG_MIN_PRO_SCORE:
        candidate_score += 6; ready_score += 5; verify_score += 3
        reasons.append(f"ICT PRO LONG onayı {safe_float(ict.get('long_pro_score', 0)):.1f}")
    if structure_score >= ICT_MIN_CHOCH_SCORE:
        verify_score += 12; reasons.append(f"CHOCH yukarı {structure_score:.1f}")
    if last_price > ema9_1[-1]:
        verify_score += 6; reasons.append("EMA9 üstü")
    if last_price > ema21_1[-1]:
        verify_score += 5; reasons.append("EMA21 üstü")
    if last_rsi1 > prev_rsi1 and last_rsi1 >= 45:
        verify_score += 5; reasons.append("RSI toparlanıyor")

    whale_score = safe_float(whale_eye.get("total_score", 0))
    whale_confidence = str(whale_eye.get("whale_confidence", "DÜŞÜK"))
    if whale_score > 0:
        reasons.append(f"🐋 Whale Eye LONG: +{whale_score:.1f} ({whale_confidence})")
        candidate_score += whale_score * 0.3
        verify_score += whale_score * 0.3
    elif whale_score < 0:
        reasons.append(f"🐋 Whale Eye LONG uyarı: {whale_score:.1f}")

    candidate_score = max(candidate_score, 0.0)
    ready_score = max(ready_score, 0.0)
    verify_score = max(verify_score, 0.0)
    total_score = candidate_score + ready_score + verify_score
    entry = last_price
    stop, tp1, tp2, tp3, rr = calculate_long_levels(entry, l1, last_atr1, last_atr1)

    quality_score = 0.0
    if ict.get("in_discount_zone"):
        quality_score += 1.4
    if ict.get("sweep_low"):
        quality_score += 1.5
    if buyer_defense:
        quality_score += 1.2
    if structure_score >= ICT_MIN_CHOCH_SCORE:
        quality_score += 1.4
    if rr >= LONG_MIN_RR_TP1:
        quality_score += 0.7
    quality_score = round(clamp(quality_score, 0.0, 10.0), 2)

    if candidate_score < LONG_MIN_CANDIDATE_SCORE:
        stage = "IGNORE"; stats["long_reject"] += 1
    elif total_score >= LONG_MIN_SIGNAL_SCORE and verify_score >= LONG_MIN_VERIFY_SCORE:
        stage = "SIGNAL"; stats["long_ict_signal"] += 1
    else:
        stage = "READY"; stats["long_ready"] += 1

    if stage == "SIGNAL" and rr < LONG_MIN_RR_TP1:
        stage = "READY"; stats["rr_block"] += 1
    if stage == "SIGNAL" and not close_gate.get("passed", False):
        stage = "READY"; stats["long_close_confirm_block"] += 1
    if stage == "SIGNAL" and quality_score < LONG_MIN_QUALITY_SCORE:
        stage = "READY"; stats["long_quality_block"] += 1

    if stage == "SIGNAL" and long_hard_blocks:
        stage = "READY"
        stats["long_conflict_block"] += 1
        reasons.extend(long_hard_blocks)

    payload = {
        "symbol": symbol, "direction": "LONG", "stage": stage,
        "signal_label": "LONG AL" if stage == "SIGNAL" else "İÇ TAKİP",
        "score": round(total_score, 2),
        "candidate_score": round(candidate_score, 2),
        "ready_score": round(ready_score, 2),
        "verify_score": round(verify_score, 2),
        "price": entry, "stop": stop, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "rr": round(rr, 2),
        "drop_10m": round(drop_10m, 2), "drop_20m": round(drop_20m, 2), "drop_1h": round(drop_1h, 2),
        "pump_10m": round(-drop_10m, 2), "pump_20m": round(-drop_20m, 2), "pump_1h": round(-drop_1h, 2),
        "rsi1": round(last_rsi1, 2), "rsi5": round(last_rsi5, 2), "rsi15": round(last_rsi15, 2),
        "vol_ratio_1m": round(vol_ratio_1m, 2), "vol_ratio_5m": round(vol_ratio_5m, 2),
        "quote_volume": quote_vol,
        "breakdown_score": structure_score, "long_structure_score": structure_score,
        "green_streak": consecutive_green_count(k1, 6), "red_count_5": recent_red_count(k1, 5),
        "quality_score": quality_score, "quality_reason": "-",
        "reason": " | ".join(reasons[:16]) if reasons else "Long sebep yok",
        "ict": ict, "long_close_gate": close_gate,
        "trade_flow": flow, "orderbook": book,
        "whale_eye": whale_eye,
        "invisible_class": "ICT LONG", "invisible_score": round(quality_score * 12.0, 1),
        "invisible_decision": "LONG_AL_SERBEST" if stage == "SIGNAL" else "LONG_TAKIP",
    }
    return enforce_single_long_al_rules(payload)


def enforce_single_short_al_rules(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = copy.deepcopy(payload)
    if p.get("stage") != "SIGNAL":
        return p

    # AI otomatik köprü sinyali geldiyse ana pump-only filtresi tekrar susturmasın.
    # Bu sinyal zaten AI yön/edge/akış/risk kapısından geçmiştir.
    if p.get("ai_auto_promoted"):
        p["signal_label"] = "SHORT AL"
        return p

    reason_text = str(p.get("reason", ""))
    pump_20m = safe_float(p.get("pump_20m", 0))
    pump_1h = safe_float(p.get("pump_1h", 0))

    whale_eye = p.get("whale_eye", {})
    whale_confidence = str(whale_eye.get("whale_confidence", "DÜŞÜK"))

    if pump_20m < 0.55 and pump_1h < 1.05 and whale_confidence not in ("ÇOK_YÜKSEK", "YÜKSEK"):
        p["stage"] = "READY"
        p["signal_label"] = "İÇ TAKİP"
        p["reason"] = f"{reason_text} | Pump zayıf, whale teyidi yok"
        stats["weak_signal_reject"] += 1
        return p

    p["signal_label"] = "SHORT AL"
    return p


def enforce_single_long_al_rules(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = copy.deepcopy(payload)
    if p.get("stage") != "SIGNAL":
        return p

    # AI otomatik köprü sinyali geldiyse LONG ICT-only filtresi tekrar susturmasın.
    # AI kendi yön/edge/akış/risk kapısından geçmedikçe buraya gelemez.
    if p.get("ai_auto_promoted"):
        p["signal_label"] = "LONG AL"
        return p

    ict = p.get("ict") if isinstance(p.get("ict"), dict) else {}
    reason = str(p.get("reason", ""))

    if ICT_REQUIRE_PRO_CONTEXT_FOR_SIGNAL and safe_float(ict.get("long_pro_score", 0)) < ICT_LONG_MIN_PRO_SCORE:
        p["stage"] = "READY"; p["signal_label"] = "İÇ TAKİP"
        p["reason"] = f"{reason} | LONG ICT PRO bağlam yetersiz"
        stats["long_quality_block"] += 1
        return p
    if not ict.get("in_discount_zone") and not ict.get("sweep_low"):
        p["stage"] = "READY"; p["signal_label"] = "İÇ TAKİP"
        p["reason"] = f"{reason} | Discount/sweep yok"
        stats["long_quality_block"] += 1
        return p

    flow = p.get("trade_flow") if isinstance(p.get("trade_flow"), dict) else {}
    sell_to_buy = safe_float(flow.get("sell_to_buy", 0))
    true_structure_up = bool(ict.get("bos_up") or ict.get("choch_up") or ict.get("mss_up"))
    if (
        LONG_BEARISH_CONTEXT_HARD_BLOCK_ENABLED
        and str(ict.get("structure_bias", "")).upper() == "BEARISH"
        and not true_structure_up
        and sell_to_buy >= LONG_SELL_TO_BUY_HARD_BLOCK
    ):
        p["stage"] = "READY"; p["signal_label"] = "İÇ TAKİP"
        p["reason"] = f"{reason} | LONG hard block: BEARISH yapı + BOS/CHOCH/MSS↑ yok + satıcı akışı x{sell_to_buy:.2f}"
        stats["long_conflict_block"] += 1
        return p

    p["signal_label"] = "LONG AL"
    return p


# =========================================================
# MESAJ FORMATLARI
# =========================================================

def format_whale_eye_block(res: Dict[str, Any]) -> str:
    whale = res.get("whale_eye") if isinstance(res.get("whale_eye"), dict) else {}
    if not whale or not whale.get("enabled"):
        return ""

    oi = whale.get("oi", {}) if isinstance(whale.get("oi"), dict) else {}
    funding = whale.get("funding", {}) if isinstance(whale.get("funding"), dict) else {}
    spoofing = whale.get("spoofing", {}) if isinstance(whale.get("spoofing"), dict) else {}
    cvd = whale.get("cvd", {}) if isinstance(whale.get("cvd"), dict) else {}

    lines = []

    # V6 WHALE EYE başlığı
    lines.append(f"\n🐋 V6 WHALE EYE - BALİNA İSTİHBARATI")
    lines.append(f"├─ Toplam Skor: {whale.get('total_score', 0)}/30")
    lines.append(f"├─ Güven Seviyesi: {whale.get('whale_confidence', '-')}")
    lines.append(f"├─ Uyumsuzluk Sayısı: {whale.get('divergence_count', 0)}")

    # Open Interest
    if oi.get("enabled") and oi.get("divergence_type", "NÖTR") != "NÖTR":
        lines.append(f"├─ OI Delta: {oi.get('divergence_type', '-')}")
        if oi.get("oi_change_pct"):
            lines.append(f"│  └─ OI Değişim: %{oi.get('oi_change_pct', 0):.2f} | Fiyat: %{oi.get('price_change_pct', 0):.2f}")

    # Funding Rate
    if funding.get("enabled") and funding.get("funding_signal", "NÖTR") != "NÖTR":
        lines.append(f"├─ Funding: {funding.get('funding_signal', '-')} (%{funding.get('funding_rate', 0):.4f})")

    # CVD
    if cvd.get("enabled") and cvd.get("divergence", "NÖTR") != "NÖTR":
        lines.append(f"├─ CVD: {cvd.get('divergence', '-')} (CVD: %{cvd.get('cvd_trend_pct', 0):.2f} | Fiyat: %{cvd.get('price_trend_pct', 0):.2f})")

    # Spoofing
    if spoofing.get("enabled") and spoofing.get("spoofing_detected"):
        lines.append(f"├─ Spoofing: {spoofing.get('spoof_type', '-')}")

    # Whale Eye yorumu
    if whale.get("reason", "") and whale.get("reason", "") != "Balina izi tespit edilmedi":
        lines.append(f"└─ Yorum: {whale.get('reason', '')[:200]}")

    return "\n".join(lines)


def format_ict_block(res: Dict[str, Any]) -> str:
    ict = res.get("ict") if isinstance(res.get("ict"), dict) else {}
    if not ict or not ict.get("enabled"):
        return ""
    return (
        f"\n🏛️ ICT PRO\n"
        f"├─ Yapı: {ict.get('structure_bias', '-')}\n"
        f"├─ BOS↑/↓: {ict.get('bos_up')}/{ict.get('bos_down')}\n"
        f"├─ CHOCH↑/↓: {ict.get('choch_up')}/{ict.get('choch_down')}\n"
        f"├─ MSS↑/↓: {ict.get('mss_up')}/{ict.get('mss_down')}\n"
        f"├─ Discount/Premium: {ict.get('in_discount_zone')}/{ict.get('in_premium_zone')}\n"
        f"├─ Sweep Alt/Üst: {ict.get('sweep_low')}/{ict.get('sweep_high')}\n"
        f"├─ SHORT PRO: {ict.get('short_pro_score', 0)}\n"
        f"└─ LONG PRO: {ict.get('long_pro_score', 0)}"
    )


def build_signal_message(res: Dict[str, Any]) -> str:
    if str(res.get("direction", "SHORT")).upper() == "LONG":
        return build_long_signal_message(res)
    signal_label = str(res.get("signal_label", "SHORT AL"))
    confirm_status = str(res.get("binance_confirm_status", "YOK"))
    binance_symbol = str(res.get("binance_symbol", "-"))
    binance_price = safe_float(res.get("binance_price", 0))
    binance_gap = safe_float(res.get("binance_price_gap_pct", 0))

    whale_eye = res.get("whale_eye", {})
    whale_confidence = str(whale_eye.get("whale_confidence", "DÜŞÜK"))
    whale_score = safe_float(whale_eye.get("total_score", 0))

    base = (
        f"🚨 {VERSION_NAME} - {signal_label}\n"
        f"⏰ {tr_str()}\n"
        f"🎯 Coin: {res['symbol']}\n"
        f"📊 Skor: {res['score']} | Kalite: {res.get('quality_score', '-')}\n"
        f"🐋 Whale Eye: {whale_confidence} ({whale_score}) | OI/Funding/CVD/Spoof\n"
        f"🟢 Aday: {res['candidate_score']} | 🟡 Hazır: {res['ready_score']} | 🔴 Doğrula: {res['verify_score']}\n"
        f"📈 Pump 10/20/1s: %{res['pump_10m']} / %{res['pump_20m']} / %{res['pump_1h']}\n"
        f"📉 RSI 1/5/15: {res['rsi1']} / {res['rsi5']} / {res['rsi15']}\n"
        f"💰 Giriş: {fmt_num(res['price'])}\n"
        f"🛑 Stop: {fmt_num(res['stop'])}\n"
        f"🎯 TP1: {fmt_num(res['tp1'])} | TP2: {fmt_num(res['tp2'])} | TP3: {fmt_num(res['tp3'])}\n"
        f"📐 RR(TP1): {res['rr']}\n"
        f"🔧 Trend Kilit: {res.get('trend_guard_score', '-')} | Kırılım: {res.get('breakdown_score', '-')}\n"
        f"📝 Not: {res['reason'][:400]}\n"
        f"📡 Veri: OKX SWAP | Binance teyit: {confirm_status}"
    )
    return base + format_whale_eye_block(res) + format_ict_block(res)


def build_long_signal_message(res: Dict[str, Any]) -> str:
    whale_eye = res.get("whale_eye", {})
    whale_confidence = str(whale_eye.get("whale_confidence", "DÜŞÜK"))
    whale_score = safe_float(whale_eye.get("total_score", 0))
    gate = res.get("long_close_gate", {}) if isinstance(res.get("long_close_gate"), dict) else {}

    base = (
        f"🚀 {VERSION_NAME} - LONG AL\n"
        f"⏰ {tr_str()}\n"
        f"🎯 Coin: {res['symbol']}\n"
        f"📊 Skor: {res['score']} | Kalite: {res.get('quality_score', '-')}\n"
        f"🐋 Whale Eye: {whale_confidence} ({whale_score}) | OI/Funding/CVD/Spoof\n"
        f"🟢 Aday: {res['candidate_score']} | 🟡 Hazır: {res['ready_score']} | 🔴 Doğrula: {res['verify_score']}\n"
        f"📉 Düşüş 10/20/1s: %{res.get('drop_10m', 0)} / %{res.get('drop_20m', 0)} / %{res.get('drop_1h', 0)}\n"
        f"📈 RSI 1/5/15: {res['rsi1']} / {res['rsi5']} / {res['rsi15']}\n"
        f"💰 Giriş: {fmt_num(res['price'])}\n"
        f"🛑 Stop: {fmt_num(res['stop'])}\n"
        f"🎯 TP1: {fmt_num(res['tp1'])} | TP2: {fmt_num(res['tp2'])} | TP3: {fmt_num(res['tp3'])}\n"
        f"📐 RR(TP1): {res['rr']}\n"
        f"📝 Not: {res['reason'][:400]}\n"
        f"📡 Veri: OKX SWAP + ICT LONG"
    )
    return base + format_whale_eye_block(res) + format_ict_block(res)


def build_heartbeat_message() -> str:
    hot_count = len(memory.get("hot", {}))
    trend_watch_count = len(memory.get("trend_watch", {}))
    last_sig = safe_float(memory.get("last_signal_ts", 0))
    last_sig_txt = tr_str(last_sig) if last_sig else "Yok"
    total_short = get_today_trade_sent_count("SHORT")
    total_long = get_today_trade_sent_count("LONG")
    total_signal = stats['signal_sent']

    follows = memory.get("follows", {})
    tp_count = sum(1 for r in follows.values() if r.get("outcome", "").startswith("TP"))
    stop_count = sum(1 for r in follows.values() if r.get("outcome") == "STOP")
    total_closed = tp_count + stop_count
    winrate = (tp_count / total_closed * 100) if total_closed > 0 else 0

    return (
        f"💓 {VERSION_NAME} DURUM\n"
        f"⏰ {tr_str()}\n"
        f"📊 Coin: {len(COINS)} | Sıcak: {hot_count} | Trend: {trend_watch_count} | Bloklu: {get_blocked_symbol_count()}\n"
        f"📨 Sinyal: SHORT {total_short}/{DAILY_SHORT_TOTAL_LIMIT} | LONG {total_long}/{LONG_DAILY_TOTAL_LIMIT} | Toplam: {total_signal}\n"
        f"🎯 Başarı: TP={tp_count} Stop={stop_count} | %{winrate:.1f}\n"
        f"📡 WebSocket: {'AÇIK' if ws_runtime_state.get('connected') else 'KAPALI'} | book={len(ws_orderbooks)} | trades={sum(len(v) for v in ws_trades.values())} | age={time.time()-safe_float(ws_runtime_state.get('last_msg_ts', 0)) if ws_runtime_state.get('last_msg_ts') else 9999:.1f}s | reconnect={ws_runtime_state.get('reconnects', 0)}\n"
        f"🐋 Whale Eye: OI={stats['oi_short_diverge']} Fund={stats['funding_short_bonus']} Spoof={stats['spoofing_detected']} CVD={stats['cvd_diverge_short']} | WS Spoof={stats.get('ws_spoofing_detected', 0)}\n"
        f"🧠 AI Otomatik: {'AÇIK' if PRO_AI_AUTOSIGNAL_LOOP_ENABLED else 'KAPALI'} | AI sinyal: {stats.get('professional_ai_auto_signal', 0)} | AI sessiz: {stats.get('professional_ai_silent', 0)}\n"
        f"🧠 AI Final: geçiş={stats.get('ai_auto_final_pass', 0)} | blok={stats.get('ai_auto_final_block', 0)} | geç short={stats.get('ai_auto_late_short_block', 0)} | geç long={stats.get('ai_auto_late_long_block', 0)}\n"
        f"🛡️ Kalite Blok: {stats['quality_gate_block']} | Kırılım Geçen: {stats['trend_breakdown_pass']} | Kapanış Blok: {stats['close_confirm_block']}\n"
        f"🧱 SR/Rejim/Makro blok: {stats.get('sr_block', 0)} / {stats.get('regime_block', 0)} / {stats.get('macro_block', 0)}\n"
        f"📉 15m MA SHORT blok: {stats.get('short_15m_ma_gate_block', 0)}\n"
        f"🧠 Hata Hafızası: öğrenme={stats.get('mistake_memory_learn', 0)} | blok={stats.get('mistake_memory_block', 0)}\n"
        f"🧪 Backtest: {stats.get('backtest_runs', 0)} | maliyetli={stats.get('backtest_cost_applied', 0)}\n"
        f"🔧 API Fail: {stats['api_fail']} | Telegram Fail: {stats['telegram_fail']} | Analiz: {stats['analyzed']}\n"
        f"📌 Son Sinyal: {last_sig_txt}\n"
        f"WS hata: {ws_runtime_state.get('last_error', '-')}"
    )


def build_hot_message(res: Dict[str, Any]) -> str:
    return (
        f"🔥 SICAK TAKİP\n"
        f"⏰ {tr_str()}\n"
        f"🎯 Coin: {res['symbol']}\n"
        f"📊 Skor: {res['score']} | Fiyat: {fmt_num(res['price'])}\n"
        f"🐋 Whale Eye: {res.get('whale_eye', {}).get('whale_confidence', '-')}\n"
        f"📝 {res['reason'][:300]}"
    )


def build_ready_message(res: Dict[str, Any]) -> str:
    return (
        f"🟠 İNCE TAKİP\n"
        f"⏰ {tr_str()}\n"
        f"🎯 Coin: {res['symbol']}\n"
        f"📊 Skor: {res['score']} | Fiyat: {fmt_num(res['price'])}\n"
        f"🐋 Whale Eye: {res.get('whale_eye', {}).get('whale_confidence', '-')}\n"
        f"📝 {res['reason'][:300]}"
    )


# =========================================================
# SİNYAL İŞLEME
# =========================================================
def signal_key(symbol: str, stage: str) -> str:
    return f"{symbol}:{stage}"


def get_signal_record(symbol: str, stage: str) -> Dict[str, Any]:
    return memory.get("signals", {}).get(signal_key(symbol, stage), {})


def better_than_previous(symbol: str, stage: str, payload: Dict[str, Any]) -> bool:
    prev = get_signal_record(symbol, stage)
    prev_score = safe_float(prev.get("score", 0))
    cur_score = safe_float(payload.get("score", 0))
    return cur_score >= prev_score + SCORE_OVERRIDE_GAP


def daily_trade_already_sent(symbol: str, direction: str) -> bool:
    direction = (direction or "SHORT").upper()
    if direction == "LONG":
        return bool(memory.get("daily_long_sent", {}).get(tr_day_key(), {}).get(symbol, {}))
    return bool(memory.get("daily_short_sent", {}).get(tr_day_key(), {}).get(symbol, {}))


def set_daily_trade_sent(symbol: str, payload: Dict[str, Any]) -> None:
    direction = str(payload.get("direction", "SHORT")).upper()
    day_key = tr_day_key()
    if direction == "LONG":
        memory.setdefault("daily_long_sent", {}).setdefault(day_key, {})[symbol] = {"ts": time.time(), "price": payload.get("price")}
    else:
        memory.setdefault("daily_short_sent", {}).setdefault(day_key, {})[symbol] = {"ts": time.time(), "price": payload.get("price")}


def get_today_trade_sent_count(direction: str) -> int:
    direction = (direction or "SHORT").upper()
    if direction == "LONG":
        return len(memory.get("daily_long_sent", {}).get(tr_day_key(), {}))
    return len(memory.get("daily_short_sent", {}).get(tr_day_key(), {}))


def get_daily_trade_limit(direction: str) -> int:
    return LONG_DAILY_TOTAL_LIMIT if (direction or "SHORT").upper() == "LONG" else DAILY_SHORT_TOTAL_LIMIT


def ai_auto_lock_key(symbol: str, direction: str) -> str:
    return f"{(direction or '').upper()}:{normalize_symbol(symbol)}"


def ai_auto_recently_locked(symbol: str, direction: str) -> bool:
    direction = (direction or "").upper()
    if direction not in ("LONG", "SHORT"):
        return False
    # Günlük kilit zaten varsa aynı coin/yön tekrar basılmasın.
    if daily_trade_already_sent(normalize_symbol(symbol), direction):
        return True
    lock_key = ai_auto_lock_key(symbol, direction)
    rec = memory.setdefault("ai_auto_sent_lock", {}).get(lock_key, {})
    last_ts = safe_float(rec.get("ts", 0)) if isinstance(rec, dict) else 0.0
    if last_ts and time.time() - last_ts < PRO_AI_AUTOSIGNAL_SAME_DIRECTION_COOLDOWN_SEC:
        return True
    # Aktif takipte aynı coin/yön varsa tekrar basma.
    follow_key = f"{direction}:{normalize_symbol(symbol)}"
    follow = memory.get("follows", {}).get(follow_key, {})
    if isinstance(follow, dict) and follow and not bool(follow.get("done", False)):
        return True
    return False


def mark_ai_auto_signal_lock(symbol: str, direction: str, payload: Optional[Dict[str, Any]] = None) -> None:
    direction = (direction or "").upper()
    if direction not in ("LONG", "SHORT"):
        return
    sym = normalize_symbol(symbol)
    memory.setdefault("ai_auto_sent_lock", {})[ai_auto_lock_key(sym, direction)] = {
        "ts": time.time(),
        "symbol": sym,
        "direction": direction,
        "price": safe_float((payload or {}).get("price", 0)),
        "score": safe_float((payload or {}).get("score", 0)),
    }


def update_hot_memory(res: Dict[str, Any]) -> None:
    res = copy.deepcopy(res)
    sym = res["symbol"]
    hot = memory.setdefault("hot", {})
    rec = hot.get(sym, {})
    hot[sym] = {
        "first_seen": rec.get("first_seen", time.time()),
        "last_seen": time.time(),
        "first_price": safe_float(rec.get("first_price", 0)) or safe_float(res.get("price", 0)),
        "last_price": res.get("price"),
        "score": max(safe_float(rec.get("score", 0)), safe_float(res.get("score", 0))),
        "whale_confidence": res.get("whale_eye", {}).get("whale_confidence", rec.get("whale_confidence", "-")),
        "reason": res.get("reason", ""),
        "updates": int(safe_float(rec.get("updates", 0))) + 1,
    }


async def confirm_signal_on_binance(res: Dict[str, Any]) -> Dict[str, Any]:
    if not BINANCE_CONFIRM_ENABLED:
        return {"status": "DISABLED", "score": 0.0, "price_gap_pct": 0.0, "binance_symbol": normalize_binance_symbol(res["symbol"]), "binance_price": 0.0, "reason": "Binance teyidi kapalı."}

    symbol = normalize_binance_symbol(res["symbol"])
    k1 = await get_binance_klines(symbol, "1m", 80)
    k5 = await get_binance_klines(symbol, "5m", 80)
    if len(k1) < 30 or len(k5) < 30:
        return {"status": "UNAVAILABLE", "score": 0.0, "price_gap_pct": 0.0, "binance_symbol": symbol, "binance_price": 0.0, "reason": "Binance teyit verisi yok."}

    c1 = closes(k1); c5 = closes(k5); h1 = highs(k1); l1 = lows(k1)
    ema9_1 = ema(c1, 9); ema21_1 = ema(c1, 21)
    rsi1 = rsi(c1, 14); rsi5 = rsi(c5, 14)

    last_price = c1[-1]; prev_price = c1[-2]
    okx_price = safe_float(res.get("price", 0))
    price_gap_pct = abs(pct_change(okx_price, last_price)) if okx_price > 0 and last_price > 0 else 0.0

    last_kline = k1[-1]
    weak_close = last_price <= safe_float(last_kline[3]) or last_price < safe_float(last_kline[1])
    bear_cross = ema9_1[-1] < ema21_1[-1] and ema9_1[-2] >= ema21_1[-2]
    micro_bear = last_price < prev_price and last_price < ema9_1[-1]
    last_rsi1 = rsi1[-1]; last_rsi5 = rsi5[-1]

    score = 0.0
    reasons: List[str] = []

    if price_gap_pct <= MAX_BINANCE_OKX_PRICE_GAP_PCT:
        score += 6.0; reasons.append(f"Fiyat farkı iyi %{price_gap_pct:.2f}")
    elif price_gap_pct <= HARD_BINANCE_OKX_PRICE_GAP_PCT:
        score -= 2.0; reasons.append(f"Fiyat farkı orta %{price_gap_pct:.2f}")
    else:
        score -= 16.0; reasons.append(f"Fiyat farkı yüksek %{price_gap_pct:.2f}")

    if micro_bear: score += 4.0; reasons.append("1dk zayıflıyor")
    if bear_cross: score += 5.0; reasons.append("EMA9/21 aşağı")
    if last_price < ema9_1[-1]: score += 4.0; reasons.append("EMA9 altı")
    if last_rsi1 < 50: score += 4.0; reasons.append("RSI1 gevşek")
    if weak_close: score += 4.0; reasons.append("Zayıf kapanış")
    if c5[-1] < c5[-2] and c5[-1] < c5[-3]: score += 4.0; reasons.append("5dk gevşeme")
    if last_rsi5 < 50: score += 2.0; reasons.append("RSI5 gevşek")

    if price_gap_pct > HARD_BINANCE_OKX_PRICE_GAP_PCT:
        status = "HARD_FAIL"
    elif score >= BINANCE_CONFIRM_SCORE_PASS:
        status = "PASS"
    elif score >= BINANCE_CONFIRM_SCORE_SOFT:
        status = "SOFT_PASS"
    else:
        status = "FAIL"

    return {"status": status, "score": round(score, 2), "price_gap_pct": round(price_gap_pct, 2), "binance_symbol": symbol, "binance_price": last_price, "reason": " | ".join(reasons[:8]) if reasons else "Binance teyit nedeni yok."}


# =========================================================
# PROFESYONEL KRİPTO YAPAY ZEKA V1 - GÖMÜLÜ MODÜL
# =========================================================
# Not: Bu modül ayrı namespace içinde çalıştırılır. Ana botun safe_float,
# fmt_num, rsi, ema, memory, stats gibi çalışan fonksiyonlarını ezmez.
# Otomatik sinyalde dışarıya sadece mevcut LONG AL / SHORT AL mesajı gider.
# Araştırma komutları: /zeka, /arastir, /yon, /ai_durum
_PROFESSIONAL_AI_CODE = r'''
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║  PROFESYONEL KRİPTO YAPAY ZEKA V1                                  ║
║  Derin Araştırma + Yön Tahmini + LONG/SHORT AL Sinyal Beyni         ║
║                                                                      ║
║  Amaç:                                                              ║
║  - Sadece hakem değil, tam kapsamlı araştırma yapan AI beyni.        ║
║  - OKX canlı piyasa verisi + orderbook + trades + OI/funding.        ║
║  - Opsiyonel haber/sosyal araştırma kaynakları.                     ║
║  - DeepSeek ile tek, kısa, katı profesyonel karar.                   ║
║  - Telegram otomatik sinyalde dışarıya sadece AL mesajı basar.       ║
║  - BEKLE/RED/AI_YOK gibi iç karar etiketlerini dışarı göstermez.     ║
║                                                                      ║
║  ÖNEMLİ: Bu dosya işlem emri göndermez. Sinyal/araştırma üretir.     ║
╚══════════════════════════════════════════════════════════════════════╝

GEREKENLER:
    pip install aiohttp python-telegram-bot>=20.0

.env / ortam değişkenleri:
    DEEPSEEK_API_KEY=sk-...
    DEEPSEEK_MODEL=deepseek-chat
    PRO_AI_ENABLED=true
    PRO_AI_FAIL_OPEN=false
    PRO_AI_MIN_CONFIDENCE=65
    PRO_AI_MIN_SIGNAL_SCORE=55
    PRO_AI_TIMEOUT_SEC=7.5

Opsiyonel araştırma API'leri:
    CRYPTOPANIC_API_KEY=...
    SERPAPI_API_KEY=...
    NEWSAPI_KEY=...

KULLANIM:
    1) Bot başlarken:
        await init_professional_crypto_ai()

    2) Bot kapanırken:
        await shutdown_professional_crypto_ai()

    3) Mevcut analyze_symbol içinde final_payload SIGNAL olduktan sonra:
        final_payload = await run_professional_ai_on_payload(
            final_payload,
            k1=k1,
            k5=k5,
            k15=k15,
            k1h=k1h,
            k4h=k4h,
            orderbook=book,
            trades=trades,
        )
        if final_payload.get("send_signal") is False:
            return final_payload

    4) Telegram handler:
        add_professional_ai_handlers(application)

Komutlar:
    /zeka BTC
    /arastir BTC
    /yon BTC
    /ai_durum

Not:
    Otomatik sinyal mesajında sadece LONG AL / SHORT AL görünür.
    Uygun değilse ekstra mesaj basmaz.
"""

from __future__ import annotations

import os
import re
import json
import time
import math
import asyncio
import hashlib
import logging
import html
from urllib.parse import quote_plus
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple
from collections import deque
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

try:
    import aiohttp
except ImportError as exc:
    raise RuntimeError("aiohttp eksik. Kurulum: pip install aiohttp") from exc


# Telegram importları opsiyonel tutuldu.
try:
    from telegram import Update
    from telegram.ext import ContextTypes, CommandHandler
    TELEGRAM_AVAILABLE = True
except Exception:
    Update = Any
    ContextTypes = Any
    CommandHandler = None
    TELEGRAM_AVAILABLE = False


# ============================================================
# GENEL AYARLAR
# ============================================================

TR_TZ = ZoneInfo(os.getenv("TIMEZONE_NAME", "Europe/Istanbul"))

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")

PRO_AI_ENABLED = os.getenv("PRO_AI_ENABLED", "true").lower() in ("1", "true", "yes", "on")
PRO_AI_FAIL_OPEN = os.getenv("PRO_AI_FAIL_OPEN", "false").lower() in ("1", "true", "yes", "on")
PRO_AI_MIN_CONFIDENCE = float(os.getenv("PRO_AI_MIN_CONFIDENCE", "65"))
PRO_AI_MIN_SIGNAL_SCORE = float(os.getenv("PRO_AI_MIN_SIGNAL_SCORE", "55"))
PRO_AI_TIMEOUT_SEC = float(os.getenv("PRO_AI_TIMEOUT_SEC", "7.5"))
PRO_AI_MAX_CALLS_PER_MIN = int(os.getenv("PRO_AI_MAX_CALLS_PER_MIN", "22"))
PRO_AI_CACHE_TTL_SEC = int(os.getenv("PRO_AI_CACHE_TTL_SEC", "90"))

OKX_BASE_URL = os.getenv("OKX_BASE_URL", "https://www.okx.com").rstrip("/")

CRYPTOPANIC_API_KEY = os.getenv("CRYPTOPANIC_API_KEY", "").strip()
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY", "").strip()
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "").strip()

# Key gerektirmeyen Google News RSS motoru
GOOGLE_NEWS_RSS_ENABLED = os.getenv("GOOGLE_NEWS_RSS_ENABLED", "true").lower() in ("1", "true", "yes", "on")
PRO_AI_EXTERNAL_RESEARCH_ON_COMMAND = os.getenv("PRO_AI_EXTERNAL_RESEARCH_ON_COMMAND", "true").lower() in ("1", "true", "yes", "on")
PRO_AI_EXTERNAL_RESEARCH_ON_SIGNAL = os.getenv("PRO_AI_EXTERNAL_RESEARCH_ON_SIGNAL", "true").lower() in ("1", "true", "yes", "on")
PRO_AI_SIGNAL_NEWS_TIMEOUT_SEC = float(os.getenv("PRO_AI_SIGNAL_NEWS_TIMEOUT_SEC", "2.0"))
PRO_AI_SIGNAL_NEWS_MAX_ITEMS = int(float(os.getenv("PRO_AI_SIGNAL_NEWS_MAX_ITEMS", "3")))

# AI yön/zeka otomatik sinyal köprüsü:
# AI raw action NO_SIGNAL dese bile; yön, skor, edge, risk ve akış birlikte güçlüyse
# içeride LONG_AL / SHORT_AL'a çevrilir. Dışarıya yine sadece AL mesajı gider.
PRO_AI_DIRECTION_AUTO_SIGNAL_ENABLED = os.getenv("PRO_AI_DIRECTION_AUTO_SIGNAL_ENABLED", "true").lower() in ("1", "true", "yes", "on")
PRO_AI_DIRECTION_MIN_CONFIDENCE = float(os.getenv("PRO_AI_DIRECTION_MIN_CONFIDENCE", "64"))
PRO_AI_DIRECTION_MIN_SIGNAL_SCORE = float(os.getenv("PRO_AI_DIRECTION_MIN_SIGNAL_SCORE", "54"))
PRO_AI_DIRECTION_MAX_RISK = float(os.getenv("PRO_AI_DIRECTION_MAX_RISK", "58"))
PRO_AI_DIRECTION_MIN_EDGE = float(os.getenv("PRO_AI_DIRECTION_MIN_EDGE", "8"))
PRO_AI_DIRECTION_MIN_FLOW_RATIO = float(os.getenv("PRO_AI_DIRECTION_MIN_FLOW_RATIO", "1.25"))
PRO_AI_DIRECTION_MAX_SHORT_DROP_FROM_PEAK_PCT = float(os.getenv("PRO_AI_DIRECTION_MAX_SHORT_DROP_FROM_PEAK_PCT", "2.20"))
PRO_AI_DIRECTION_MAX_LONG_BOUNCE_FROM_LOW_PCT = float(os.getenv("PRO_AI_DIRECTION_MAX_LONG_BOUNCE_FROM_LOW_PCT", "2.20"))

logger = logging.getLogger("professional_crypto_ai")
if not logger.handlers:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


professional_ai: Optional["ProfessionalCryptoAI"] = None


# ============================================================
# YARDIMCI FONKSİYONLAR
# ============================================================

def now_ts() -> float:
    return time.time()


def tr_now_str() -> str:
    return datetime.now(TR_TZ).strftime("%d.%m.%Y %H:%M:%S")


def safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        if isinstance(x, str) and x.strip() in ("", "-", "None", "nan"):
            return default
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except Exception:
        return default


def safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(float(x))
    except Exception:
        return default


def avg(values: List[float], default: float = 0.0) -> float:
    vals = [safe_float(v) for v in values if v is not None]
    return sum(vals) / len(vals) if vals else default


def pct_change(old: float, new: float) -> float:
    old = safe_float(old)
    new = safe_float(new)
    if old == 0:
        return 0.0
    return (new - old) / abs(old) * 100.0


def fmt_num(x: Any, digits: int = 6) -> str:
    v = safe_float(x)
    if abs(v) >= 1000:
        return f"{v:.2f}"
    if abs(v) >= 100:
        return f"{v:.3f}"
    if abs(v) >= 10:
        return f"{v:.4f}"
    if abs(v) >= 1:
        return f"{v:.5f}"
    return f"{v:.{digits}f}"


def normalize_symbol(symbol: str) -> str:
    s = (symbol or "").upper().strip()
    s = s.replace("/", "-").replace("_", "-")
    s = s.replace("USDTUSDT", "USDT")
    if "-USDT-SWAP" in s:
        return s
    if s.endswith("USDT-SWAP") and "-" not in s:
        base = s.replace("USDT-SWAP", "")
        return f"{base}-USDT-SWAP"
    if s.endswith("USDT") and "-USDT" not in s:
        base = s[:-4]
        return f"{base}-USDT-SWAP"
    if s.endswith("-USDT"):
        base = s.replace("-USDT", "")
        return f"{base}-USDT-SWAP"
    if "-" not in s:
        return f"{s}-USDT-SWAP"
    return s


def base_coin(symbol: str) -> str:
    s = normalize_symbol(symbol)
    return s.split("-")[0]


def closes(klines: List[List[Any]]) -> List[float]:
    return [safe_float(k[4]) for k in klines if len(k) > 4]


def opens(klines: List[List[Any]]) -> List[float]:
    return [safe_float(k[1]) for k in klines if len(k) > 1]


def highs(klines: List[List[Any]]) -> List[float]:
    return [safe_float(k[2]) for k in klines if len(k) > 2]


def lows(klines: List[List[Any]]) -> List[float]:
    return [safe_float(k[3]) for k in klines if len(k) > 3]


def volumes(klines: List[List[Any]]) -> List[float]:
    # OKX candles: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
    return [safe_float(k[5]) for k in klines if len(k) > 5]


def ema(values: List[float], period: int) -> List[float]:
    vals = [safe_float(v) for v in values]
    if not vals:
        return []
    if period <= 1:
        return vals[:]
    alpha = 2.0 / (period + 1.0)
    out: List[float] = []
    seed_len = min(period, len(vals))
    seed = avg(vals[:seed_len], vals[0])
    prev = seed
    for i, v in enumerate(vals):
        if i < seed_len - 1:
            out.append(avg(vals[: i + 1], v))
        elif i == seed_len - 1:
            out.append(seed)
        else:
            prev = (v * alpha) + (prev * (1.0 - alpha))
            out.append(prev)
    return out


def rsi_wilder(values: List[float], period: int = 14) -> List[float]:
    vals = [safe_float(v) for v in values]
    if len(vals) < 2:
        return [50.0] * len(vals)
    deltas = [vals[i] - vals[i - 1] for i in range(1, len(vals))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [abs(min(d, 0.0)) for d in deltas]

    out = [50.0] * len(vals)
    if len(deltas) < period:
        return out

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rs = avg_gain / avg_loss if avg_loss != 0 else 999.0
    out[period] = 100.0 - (100.0 / (1.0 + rs))

    for i in range(period + 1, len(vals)):
        gain = gains[i - 1]
        loss = losses[i - 1]
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
        rs = avg_gain / avg_loss if avg_loss != 0 else 999.0
        out[i] = 100.0 - (100.0 / (1.0 + rs))
    return out


def atr(klines: List[List[Any]], period: int = 14) -> List[float]:
    if not klines:
        return []
    h = highs(klines)
    l = lows(klines)
    c = closes(klines)
    trs: List[float] = []
    for i in range(len(c)):
        if i == 0:
            trs.append(max(h[i] - l[i], 0.0))
        else:
            trs.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    if len(trs) < period:
        return [avg(trs)] * len(trs)
    out: List[float] = []
    prev = avg(trs[:period])
    for i, tr in enumerate(trs):
        if i < period - 1:
            out.append(avg(trs[: i + 1]))
        elif i == period - 1:
            out.append(prev)
        else:
            prev = ((prev * (period - 1)) + tr) / period
            out.append(prev)
    return out


def json_dumps_compact(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", text.strip(), flags=re.I)
    try:
        obj = json.loads(cleaned)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass

    # Dengeli süslü parantez arama
    start = cleaned.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(cleaned[start : i + 1])
                        return obj if isinstance(obj, dict) else None
                    except Exception:
                        return None
    return None


# ============================================================
# HTTP / RATE LIMIT / CACHE
# ============================================================

class SimpleTTLCache:
    def __init__(self, max_size: int = 800):
        self.max_size = max_size
        self._data: Dict[str, Tuple[Any, float, int]] = {}
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[Any]:
        item = self._data.get(key)
        if not item:
            self.misses += 1
            return None
        value, ts, ttl = item
        if now_ts() - ts > ttl:
            self._data.pop(key, None)
            self.misses += 1
            return None
        self.hits += 1
        return value

    def set(self, key: str, value: Any, ttl: int = 60) -> None:
        if len(self._data) >= self.max_size:
            oldest = sorted(self._data.items(), key=lambda kv: kv[1][1])
            for k, _ in oldest[: max(1, int(self.max_size * 0.20))]:
                self._data.pop(k, None)
        self._data[key] = (value, now_ts(), ttl)

    def clear(self) -> None:
        self._data.clear()
        self.hits = 0
        self.misses = 0

    def stats(self) -> Dict[str, Any]:
        total = self.hits + self.misses
        return {
            "size": len(self._data),
            "max_size": self.max_size,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round((self.hits / total * 100) if total else 0.0, 2),
        }


class MinuteRateLimiter:
    def __init__(self, max_per_minute: int):
        self.max_per_minute = max_per_minute
        self.window_start = now_ts()
        self.count = 0

    def allow(self) -> bool:
        t = now_ts()
        if t - self.window_start >= 60:
            self.window_start = t
            self.count = 0
        if self.count >= self.max_per_minute:
            return False
        self.count += 1
        return True


class HTTPClient:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache = SimpleTTLCache(max_size=1200)

    async def ensure(self) -> None:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=12)
            self.session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    async def get_json(self, url: str, params: Optional[Dict[str, Any]] = None, ttl: int = 8) -> Dict[str, Any]:
        await self.ensure()
        params = params or {}
        key = "GET:" + url + ":" + json_dumps_compact(params)
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        try:
            async with self.session.get(url, params=params) as resp:
                text = await resp.text()
                if resp.status != 200:
                    return {"_ok": False, "_status": resp.status, "_error": text[:300]}
                data = json.loads(text)
                if isinstance(data, dict):
                    data["_ok"] = True
                self.cache.set(key, data, ttl)
                return data
        except Exception as e:
            return {"_ok": False, "_error": str(e)[:220]}

    async def post_json(
        self,
        url: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        ttl: int = 0,
        timeout_sec: float = 10.0,
    ) -> Dict[str, Any]:
        await self.ensure()
        headers = headers or {}
        key = "POST:" + url + ":" + hashlib.sha256(json_dumps_compact(payload).encode()).hexdigest()
        if ttl > 0:
            cached = self.cache.get(key)
            if cached is not None:
                return cached

        try:
            timeout = aiohttp.ClientTimeout(total=timeout_sec)
            async with self.session.post(url, json=payload, headers=headers, timeout=timeout) as resp:
                text = await resp.text()
                if resp.status != 200:
                    return {"_ok": False, "_status": resp.status, "_error": text[:500]}
                data = json.loads(text)
                if isinstance(data, dict):
                    data["_ok"] = True
                if ttl > 0:
                    self.cache.set(key, data, ttl)
                return data
        except asyncio.TimeoutError:
            return {"_ok": False, "_error": "timeout"}
        except Exception as e:
            return {"_ok": False, "_error": str(e)[:220]}


# ============================================================
# OKX VERİ MOTORU
# ============================================================

class OKXResearchData:
    def __init__(self, http: HTTPClient):
        self.http = http

    async def ticker(self, inst_id: str) -> Dict[str, Any]:
        url = f"{OKX_BASE_URL}/api/v5/market/ticker"
        data = await self.http.get_json(url, {"instId": inst_id}, ttl=4)
        rows = data.get("data") or []
        return rows[0] if rows else {}

    async def candles(self, inst_id: str, bar: str = "1m", limit: int = 120) -> List[List[Any]]:
        url = f"{OKX_BASE_URL}/api/v5/market/candles"
        data = await self.http.get_json(url, {"instId": inst_id, "bar": bar, "limit": str(limit)}, ttl=8)
        rows = data.get("data") or []
        # OKX yeni mumları önce döndürür, eski -> yeni sıraya çeviriyoruz
        rows = list(reversed(rows))
        return rows

    async def orderbook(self, inst_id: str, sz: int = 50) -> Dict[str, Any]:
        url = f"{OKX_BASE_URL}/api/v5/market/books"
        data = await self.http.get_json(url, {"instId": inst_id, "sz": str(sz)}, ttl=3)
        rows = data.get("data") or []
        if not rows:
            return {}
        book = rows[0]
        bids = book.get("bids") or []
        asks = book.get("asks") or []
        bid_total = sum(safe_float(x[1]) * safe_float(x[0]) for x in bids)
        ask_total = sum(safe_float(x[1]) * safe_float(x[0]) for x in asks)
        bid_near = sum(safe_float(x[1]) * safe_float(x[0]) for x in bids[:10])
        ask_near = sum(safe_float(x[1]) * safe_float(x[0]) for x in asks[:10])
        best_bid = safe_float(bids[0][0]) if bids else 0
        best_ask = safe_float(asks[0][0]) if asks else 0
        mid = (best_bid + best_ask) / 2 if best_bid and best_ask else 0
        spread_pct = pct_change(best_bid, best_ask) if best_bid else 0
        pressure = (ask_near - bid_near) / max(ask_near + bid_near, 1)
        return {
            "raw": book,
            "bids": bids,
            "asks": asks,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid": mid,
            "spread_pct": spread_pct,
            "bid_total": bid_total,
            "ask_total": ask_total,
            "bid_near": bid_near,
            "ask_near": ask_near,
            "book_pressure": pressure,
        }

    async def trades(self, inst_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        url = f"{OKX_BASE_URL}/api/v5/market/trades"
        data = await self.http.get_json(url, {"instId": inst_id, "limit": str(limit)}, ttl=3)
        rows = data.get("data") or []
        out = []
        for r in rows:
            px = safe_float(r.get("px"))
            sz = safe_float(r.get("sz"))
            side = str(r.get("side") or "").lower()
            out.append({
                "px": px,
                "sz": sz,
                "side": side,
                "notional": px * sz,
                "ts": safe_float(r.get("ts")),
            })
        return out

    async def funding_rate(self, inst_id: str) -> Dict[str, Any]:
        url = f"{OKX_BASE_URL}/api/v5/public/funding-rate"
        data = await self.http.get_json(url, {"instId": inst_id}, ttl=60)
        rows = data.get("data") or []
        return rows[0] if rows else {}

    async def open_interest(self, inst_id: str) -> Dict[str, Any]:
        url = f"{OKX_BASE_URL}/api/v5/public/open-interest"
        data = await self.http.get_json(url, {"instType": "SWAP", "instId": inst_id}, ttl=20)
        rows = data.get("data") or []
        return rows[0] if rows else {}

    async def collect_market_pack(self, inst_id: str) -> Dict[str, Any]:
        inst_id = normalize_symbol(inst_id)
        tasks = {
            "ticker": self.ticker(inst_id),
            "k1": self.candles(inst_id, "1m", 180),
            "k5": self.candles(inst_id, "5m", 160),
            "k15": self.candles(inst_id, "15m", 160),
            "k1h": self.candles(inst_id, "1H", 120),
            "k4h": self.candles(inst_id, "4H", 80),
            "book": self.orderbook(inst_id, 50),
            "trades": self.trades(inst_id, 120),
            "funding": self.funding_rate(inst_id),
            "oi": self.open_interest(inst_id),
        }
        results: Dict[str, Any] = {}
        for name, coro in tasks.items():
            try:
                results[name] = await asyncio.wait_for(coro, timeout=5.5)
            except Exception as e:
                results[name] = {} if name not in ("k1", "k5", "k15", "k1h", "k4h", "trades") else []
                logger.warning("OKX veri hatası %s %s: %s", inst_id, name, str(e)[:100])
        results["symbol"] = inst_id
        return results


# ============================================================
# OPSİYONEL HABER / DIŞ ARAŞTIRMA
# ============================================================

class ExternalResearchEngine:
    def __init__(self, http: HTTPClient):
        self.http = http

    async def cryptopanic(self, coin: str) -> List[Dict[str, Any]]:
        if not CRYPTOPANIC_API_KEY:
            return []
        url = "https://cryptopanic.com/api/developer/v2/posts/"
        params = {
            "auth_token": CRYPTOPANIC_API_KEY,
            "currencies": coin,
            "public": "true",
        }
        data = await self.http.get_json(url, params, ttl=180)
        rows = data.get("results") or []
        out = []
        for r in rows[:10]:
            out.append({
                "source": "cryptopanic",
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "published_at": r.get("published_at", ""),
                "kind": r.get("kind", ""),
                "votes": r.get("votes", {}),
            })
        return out

    async def google_news_rss(self, coin: str, max_items: int = 8) -> List[Dict[str, Any]]:
        """
        Google News RSS: ücretsiz, API key istemez.
        Komutla araştırmada ve istenirse otomatik sinyalde haber başlığı toplar.
        """
        if not GOOGLE_NEWS_RSS_ENABLED:
            return []

        query = f"{coin} crypto OR {coin} cryptocurrency"
        url = "https://news.google.com/rss/search"
        params = {
            "q": query,
            "hl": "tr",
            "gl": "TR",
            "ceid": "TR:tr",
        }

        await self.http.ensure()
        try:
            async with self.http.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=PRO_AI_SIGNAL_NEWS_TIMEOUT_SEC)) as resp:
                if resp.status != 200:
                    return []
                xml = await resp.text()
        except Exception:
            return []

        items: List[Dict[str, Any]] = []
        blocks = re.findall(r"<item>(.*?)</item>", xml, flags=re.S | re.I)
        for block in blocks[:max_items]:
            title_m = re.search(r"<title>(.*?)</title>", block, flags=re.S | re.I)
            link_m = re.search(r"<link>(.*?)</link>", block, flags=re.S | re.I)
            date_m = re.search(r"<pubDate>(.*?)</pubDate>", block, flags=re.S | re.I)
            source_m = re.search(r"<source[^>]*>(.*?)</source>", block, flags=re.S | re.I)

            title = html.unescape(re.sub(r"<.*?>", "", title_m.group(1))).strip() if title_m else ""
            link = html.unescape(link_m.group(1)).strip() if link_m else ""
            pub_date = html.unescape(date_m.group(1)).strip() if date_m else ""
            source = html.unescape(re.sub(r"<.*?>", "", source_m.group(1))).strip() if source_m else "Google News RSS"

            if not title:
                continue

            items.append({
                "source": f"google_news_rss:{source}",
                "title": title,
                "url": link,
                "published_at": pub_date,
                "snippet": "",
            })

        return items

    async def serpapi_news(self, coin: str) -> List[Dict[str, Any]]:
        if not SERPAPI_API_KEY:
            return []
        q = f"{coin} crypto news price analysis"
        url = "https://serpapi.com/search.json"
        params = {
            "engine": "google_news",
            "q": q,
            "api_key": SERPAPI_API_KEY,
            "hl": "en",
            "gl": "us",
        }
        data = await self.http.get_json(url, params, ttl=240)
        rows = data.get("news_results") or []
        out = []
        for r in rows[:10]:
            out.append({
                "source": "serpapi_google_news",
                "title": r.get("title", ""),
                "url": r.get("link", ""),
                "published_at": r.get("date", ""),
                "snippet": r.get("snippet", ""),
            })
        return out

    async def newsapi(self, coin: str) -> List[Dict[str, Any]]:
        if not NEWSAPI_KEY:
            return []
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": f"{coin} crypto OR {coin} cryptocurrency",
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": "10",
            "apiKey": NEWSAPI_KEY,
        }
        data = await self.http.get_json(url, params, ttl=240)
        rows = data.get("articles") or []
        out = []
        for r in rows[:10]:
            out.append({
                "source": "newsapi",
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "published_at": r.get("publishedAt", ""),
                "snippet": r.get("description", ""),
            })
        return out

    async def collect(self, symbol: str, max_items: int = 15) -> Dict[str, Any]:
        coin = base_coin(symbol)
        tasks = [
            self.google_news_rss(coin, max_items=max(3, min(PRO_AI_SIGNAL_NEWS_MAX_ITEMS if max_items <= 3 else max_items, 10))),
            self.cryptopanic(coin),
            self.serpapi_news(coin),
            self.newsapi(coin),
        ]
        results: List[Dict[str, Any]] = []
        for coro in tasks:
            try:
                rows = await asyncio.wait_for(coro, timeout=PRO_AI_SIGNAL_NEWS_TIMEOUT_SEC if max_items <= 3 else 4.5)
                if rows:
                    results.extend(rows)
            except Exception:
                pass

        # başlık dedupe
        seen = set()
        unique = []
        for x in results:
            title = (x.get("title") or "").strip()
            if not title:
                continue
            key = title.lower()[:120]
            if key in seen:
                continue
            seen.add(key)
            unique.append(x)

        return {
            "coin": coin,
            "enabled_sources": {
                "google_news_rss": bool(GOOGLE_NEWS_RSS_ENABLED),
                "cryptopanic": bool(CRYPTOPANIC_API_KEY),
                "serpapi": bool(SERPAPI_API_KEY),
                "newsapi": bool(NEWSAPI_KEY),
            },
            "items": unique[:max_items],
        }


# ============================================================
# PİYASA ÖZET / SKOR MOTORLARI
# ============================================================

@dataclass
class TechnicalSnapshot:
    symbol: str
    price: float
    change_10m: float
    change_20m: float
    change_1h: float
    change_4h: float
    rsi_1m: float
    rsi_5m: float
    rsi_15m: float
    ema_state_1m: str
    ema_state_5m: str
    ema_state_15m: str
    market_structure: str
    pump_context: float
    near_peak_pct: float
    drop_from_peak_pct: float
    atr_pct_1m: float
    volume_1m_mult: float
    volume_5m_mult: float


@dataclass
class FlowSnapshot:
    book_pressure: float
    spread_pct: float
    bid_near: float
    ask_near: float
    buy_notional: float
    sell_notional: float
    sell_buy_ratio: float
    buy_sell_ratio: float
    large_buy_count: int
    large_sell_count: int
    flow_direction: str


@dataclass
class DerivativesSnapshot:
    funding_rate: float
    funding_time: str
    open_interest: float
    oi_currency: str
    oi_available: bool
    funding_available: bool


def tf_summary_from_klines(symbol: str, market_pack: Dict[str, Any]) -> TechnicalSnapshot:
    k1 = market_pack.get("k1") or []
    k5 = market_pack.get("k5") or []
    k15 = market_pack.get("k15") or []
    k1h = market_pack.get("k1h") or []
    k4h = market_pack.get("k4h") or []
    ticker = market_pack.get("ticker") or {}

    c1 = closes(k1)
    c5 = closes(k5)
    c15 = closes(k15)
    c1h = closes(k1h)
    c4h = closes(k4h)

    price = safe_float(ticker.get("last")) or (c1[-1] if c1 else 0.0)

    r1 = rsi_wilder(c1)[-1] if c1 else 50.0
    r5 = rsi_wilder(c5)[-1] if c5 else 50.0
    r15 = rsi_wilder(c15)[-1] if c15 else 50.0

    def ema_state(c: List[float]) -> str:
        if len(c) < 30:
            return "YETERSIZ"
        e9 = ema(c, 9)[-1]
        e21 = ema(c, 21)[-1]
        e50 = ema(c, 50)[-1] if len(c) >= 50 else e21
        last = c[-1]
        if last > e9 > e21 > e50:
            return "GÜÇLÜ_YUKARI"
        if last < e9 < e21 < e50:
            return "GÜÇLÜ_AŞAĞI"
        if last > e21:
            return "YUKARI_EĞİLİM"
        if last < e21:
            return "AŞAĞI_EĞİLİM"
        return "RANGE"

    ema1 = ema_state(c1)
    ema5 = ema_state(c5)
    ema15 = ema_state(c15)

    # Basit structure: son swing yüksek/düşük
    structure = "RANGE"
    if len(c15) >= 40:
        recent_high = max(c15[-20:])
        prev_high = max(c15[-40:-20])
        recent_low = min(c15[-20:])
        prev_low = min(c15[-40:-20])
        if recent_high > prev_high and recent_low > prev_low:
            structure = "BULLISH"
        elif recent_high < prev_high and recent_low < prev_low:
            structure = "BEARISH"

    ch10 = pct_change(c1[-10], c1[-1]) if len(c1) >= 10 else 0
    ch20 = pct_change(c1[-20], c1[-1]) if len(c1) >= 20 else 0
    ch1h = pct_change(c1[-60], c1[-1]) if len(c1) >= 60 else (pct_change(c5[-12], c5[-1]) if len(c5) >= 12 else 0)
    ch4h = pct_change(c15[-16], c15[-1]) if len(c15) >= 16 else 0

    h1 = highs(k1)
    recent_peak = max(h1[-90:]) if len(h1) >= 20 else (max(h1) if h1 else price)
    drop_from_peak = pct_change(recent_peak, price) * -1 if recent_peak else 0
    near_peak_pct = abs(pct_change(recent_peak, price)) if recent_peak else 0

    a1 = atr(k1, 14)
    atr_pct = (a1[-1] / price * 100) if a1 and price else 0

    v1 = volumes(k1)
    v5 = volumes(k5)
    vol1_mult = (v1[-1] / max(avg(v1[-30:-1]), 1e-9)) if len(v1) >= 31 else 1.0
    vol5_mult = (v5[-1] / max(avg(v5[-30:-1]), 1e-9)) if len(v5) >= 31 else 1.0

    pump_context = max(ch10, ch20, ch1h, ch4h, 0)

    return TechnicalSnapshot(
        symbol=symbol,
        price=price,
        change_10m=round(ch10, 3),
        change_20m=round(ch20, 3),
        change_1h=round(ch1h, 3),
        change_4h=round(ch4h, 3),
        rsi_1m=round(r1, 2),
        rsi_5m=round(r5, 2),
        rsi_15m=round(r15, 2),
        ema_state_1m=ema1,
        ema_state_5m=ema5,
        ema_state_15m=ema15,
        market_structure=structure,
        pump_context=round(pump_context, 3),
        near_peak_pct=round(near_peak_pct, 3),
        drop_from_peak_pct=round(drop_from_peak, 3),
        atr_pct_1m=round(atr_pct, 3),
        volume_1m_mult=round(vol1_mult, 3),
        volume_5m_mult=round(vol5_mult, 3),
    )


def flow_snapshot(market_pack: Dict[str, Any]) -> FlowSnapshot:
    book = market_pack.get("book") or {}
    trades = market_pack.get("trades") or []

    buy_notional = 0.0
    sell_notional = 0.0
    large_buy = 0
    large_sell = 0

    for t in trades:
        side = str(t.get("side") or "").lower()
        n = safe_float(t.get("notional"))
        if side == "buy":
            buy_notional += n
            if n >= 25_000:
                large_buy += 1
        elif side == "sell":
            sell_notional += n
            if n >= 25_000:
                large_sell += 1

    sell_buy = sell_notional / max(buy_notional, 1.0)
    buy_sell = buy_notional / max(sell_notional, 1.0)

    pressure = safe_float(book.get("book_pressure"))
    if sell_buy > 1.35 and pressure >= -0.15:
        direction = "SATIŞ_BASKIN"
    elif buy_sell > 1.35 and pressure <= 0.15:
        direction = "ALIŞ_BASKIN"
    else:
        direction = "DENGELİ"

    return FlowSnapshot(
        book_pressure=round(pressure, 4),
        spread_pct=round(safe_float(book.get("spread_pct")), 4),
        bid_near=round(safe_float(book.get("bid_near")), 2),
        ask_near=round(safe_float(book.get("ask_near")), 2),
        buy_notional=round(buy_notional, 2),
        sell_notional=round(sell_notional, 2),
        sell_buy_ratio=round(sell_buy, 3),
        buy_sell_ratio=round(buy_sell, 3),
        large_buy_count=large_buy,
        large_sell_count=large_sell,
        flow_direction=direction,
    )


def derivatives_snapshot(market_pack: Dict[str, Any]) -> DerivativesSnapshot:
    funding = market_pack.get("funding") or {}
    oi = market_pack.get("oi") or {}

    fr = safe_float(funding.get("fundingRate")) * 100.0 if funding else 0.0
    oi_val = safe_float(oi.get("oi"))
    oi_ccy = str(oi.get("oiCcy") or "")

    return DerivativesSnapshot(
        funding_rate=round(fr, 5),
        funding_time=str(funding.get("fundingTime") or ""),
        open_interest=oi_val,
        oi_currency=oi_ccy,
        oi_available=bool(oi),
        funding_available=bool(funding),
    )


def deterministic_direction_score(tech: TechnicalSnapshot, flow: FlowSnapshot, der: DerivativesSnapshot) -> Dict[str, Any]:
    """
    LLM'den önce kaba yön skoru. Amaç: AI'a sağlam, sayısal omurga vermek.
    """
    long_score = 0.0
    short_score = 0.0
    notes: List[str] = []

    # EMA / trend
    for state, weight in [
        (tech.ema_state_1m, 7),
        (tech.ema_state_5m, 10),
        (tech.ema_state_15m, 12),
    ]:
        if "GÜÇLÜ_YUKARI" in state:
            long_score += weight
        elif "GÜÇLÜ_AŞAĞI" in state:
            short_score += weight
        elif "YUKARI" in state:
            long_score += weight * 0.55
        elif "AŞAĞI" in state:
            short_score += weight * 0.55

    if tech.market_structure == "BULLISH":
        long_score += 14
        notes.append("15m yapı bullish")
    elif tech.market_structure == "BEARISH":
        short_score += 14
        notes.append("15m yapı bearish")

    # Pump tepe short context
    if tech.pump_context >= 1.2 and tech.near_peak_pct <= 0.90:
        short_score += 14
        notes.append("pump sonrası tepeye yakın")
    elif tech.pump_context >= 2.2 and tech.drop_from_peak_pct <= 1.6:
        short_score += 10
        notes.append("pump sonrası erken geri çekilme")

    # RSI
    if tech.rsi_5m >= 70 or tech.rsi_15m >= 70:
        short_score += 8
        notes.append("RSI aşırı ısınma")
    if tech.rsi_5m <= 32 or tech.rsi_15m <= 32:
        long_score += 8
        notes.append("RSI aşırı satış")

    # Flow
    if flow.flow_direction == "SATIŞ_BASKIN":
        short_score += 18
        notes.append(f"satış akışı baskın x{flow.sell_buy_ratio}")
    elif flow.flow_direction == "ALIŞ_BASKIN":
        long_score += 18
        notes.append(f"alış akışı baskın x{flow.buy_sell_ratio}")

    if flow.large_sell_count > flow.large_buy_count:
        short_score += min(8, (flow.large_sell_count - flow.large_buy_count) * 2)
    elif flow.large_buy_count > flow.large_sell_count:
        long_score += min(8, (flow.large_buy_count - flow.large_sell_count) * 2)

    # Funding
    if der.funding_available:
        if der.funding_rate >= 0.05:
            short_score += 5
            notes.append("pozitif/aşırı funding short lehine")
        elif der.funding_rate <= -0.05:
            long_score += 5
            notes.append("negatif funding long lehine")

    # Hacim
    if tech.volume_1m_mult >= 1.4 or tech.volume_5m_mult >= 1.25:
        if flow.flow_direction == "SATIŞ_BASKIN":
            short_score += 6
        elif flow.flow_direction == "ALIŞ_BASKIN":
            long_score += 6

    # Yatay / gecikme riskleri
    risk_flags = []
    if tech.pump_context < 0.35 and max(abs(tech.change_20m), abs(tech.change_1h)) < 0.5:
        risk_flags.append("hareket zayıf/yatay")
    if tech.atr_pct_1m <= 0.08:
        risk_flags.append("volatilite düşük")
    if flow.spread_pct > 0.12:
        risk_flags.append("spread geniş")
    if tech.drop_from_peak_pct > 2.2 and flow.flow_direction != "SATIŞ_BASKIN":
        risk_flags.append("düşüş kaçmış/geç kalma riski")

    direction = "RANGE"
    raw_edge = abs(long_score - short_score)
    if short_score >= long_score + 8:
        direction = "AŞAĞI"
    elif long_score >= short_score + 8:
        direction = "YUKARI"

    return {
        "long_score": round(long_score, 2),
        "short_score": round(short_score, 2),
        "edge": round(raw_edge, 2),
        "direction": direction,
        "notes": notes[:8],
        "risk_flags": risk_flags,
    }


def build_trade_levels(symbol: str, direction: str, price: float, tech: TechnicalSnapshot) -> Dict[str, float]:
    """
    Sinyal seviyeleri. Ana bot seviyeleri varsa payload'dan korunmalı.
    Bu fonksiyon research komutları için yedek seviye üretir.
    """
    atr_abs = max(price * tech.atr_pct_1m / 100.0, price * 0.004)
    if direction == "SHORT":
        stop = price + max(atr_abs * 1.6, price * 0.0075)
        tp1 = price * 0.990
        tp2 = price * 0.985
        tp3 = price * 0.980
    elif direction == "LONG":
        stop = price - max(atr_abs * 1.6, price * 0.0075)
        tp1 = price * 1.010
        tp2 = price * 1.015
        tp3 = price * 1.020
    else:
        stop = tp1 = tp2 = tp3 = 0.0
    return {
        "entry": price,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
    }


# ============================================================
# DEEPSEEK AI MOTORU
# ============================================================

class DeepSeekResearchBrain:
    def __init__(self, http: HTTPClient):
        self.http = http
        self.rate = MinuteRateLimiter(PRO_AI_MAX_CALLS_PER_MIN)
        self.cache = SimpleTTLCache(max_size=400)
        self.error_count = 0
        self.circuit_until = 0.0

    @property
    def enabled(self) -> bool:
        return bool(DEEPSEEK_API_KEY) and PRO_AI_ENABLED

    async def ask_json(self, system_prompt: str, user_prompt: str, timeout_sec: float = PRO_AI_TIMEOUT_SEC) -> Dict[str, Any]:
        if not self.enabled:
            return {"success": False, "parsed": None, "content": "", "error": "AI kapalı veya API key yok"}

        if now_ts() < self.circuit_until:
            return {"success": False, "parsed": None, "content": "", "error": "AI devre kesici aktif"}

        if not self.rate.allow():
            return {"success": False, "parsed": None, "content": "", "error": "AI rate limit"}

        key = hashlib.sha256((system_prompt + "\n" + user_prompt).encode("utf-8")).hexdigest()
        cached = self.cache.get(key)
        if cached:
            return cached

        url = f"{DEEPSEEK_BASE_URL}/chat/completions"
        payload = {
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.18,
            "max_tokens": 900,
            "top_p": 0.82,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        }

        data = await self.http.post_json(url, payload, headers=headers, ttl=0, timeout_sec=timeout_sec)
        if not data.get("_ok"):
            self.error_count += 1
            if self.error_count >= 5:
                self.circuit_until = now_ts() + 90
            return {"success": False, "parsed": None, "content": "", "error": data.get("_error", "API hata")}

        try:
            content = data["choices"][0]["message"]["content"].strip()
        except Exception:
            return {"success": False, "parsed": None, "content": "", "error": "AI cevap formatı bozuk"}

        parsed = extract_json_object(content)
        if not parsed:
            return {"success": False, "parsed": None, "content": content, "error": "JSON parse edilemedi"}

        self.error_count = 0
        result = {"success": True, "parsed": parsed, "content": content, "error": ""}
        self.cache.set(key, result, PRO_AI_CACHE_TTL_SEC)
        return result


PRO_SYSTEM_PROMPT = """
Sen profesyonel bir kripto piyasa araştırma ve yön tahmin motorusun.
Görevin: eldeki canlı piyasa verisi, order flow, türev verisi, haber/sosyal araştırma ve teknik yapıyı birlikte yorumlayıp coin'in kısa vadede YUKARI mı AŞAĞI mı gitme ihtimali daha yüksek söylemektir.

Kesin kurallar:
- Dışarıya BEKLE, SHORT_ONAY, SHORT_RED, GEC_KALDIN, AI_YOK gibi karar etiketleri üretme.
- JSON dışında cevap yazma.
- Sinyal üretilecekse sadece action alanında LONG_AL veya SHORT_AL kullan.
- Sinyal net değilse action NO_SIGNAL olsun, ama bunu kullanıcı mesajına basmayacağız.
- Uydurma haber yazma. Haber yoksa "haber_yok" de.
- Sadece RSI/EMA ezberi yapma. Likidite, pump/tepe, satış-alış akışı, trend devamı, geç kalma ve stop avı riskini önemse.
- Düşüş kaçmışsa SHORT_AL verme.
- Yükseliş hâlâ güçlü ve satış devralması yoksa SHORT_AL verme.
- Düşüş yapısı hâlâ güçlü ve alıcı devralması yoksa LONG_AL verme.
- Confidence 0-100 arası gerçekçi olmalı.
- signal_score 0-100 arası olmalı.
- risk 0-100 arası olmalı, yüksek riskte sinyal verme.
- Sinyal varsa kısa ve net sebep yaz.
- Stop/TP seviyeleri sayısal olmalı, ama verilen seviyeler mantıksızsa düzeltme öner.
JSON şeması:
{
  "action": "LONG_AL|SHORT_AL|NO_SIGNAL",
  "direction": "YUKARI|AŞAĞI|RANGE",
  "confidence": 0-100,
  "signal_score": 0-100,
  "risk": 0-100,
  "market_regime": "PUMP_DEVAM|TEPE_DAGITIM|DUSUS_DEVAM|DIP_TOPLAMA|RANGE|KARISIK",
  "research_summary": "kısa araştırma özeti",
  "main_reasons": ["neden1","neden2","neden3"],
  "danger_flags": ["risk1","risk2"],
  "entry_comment": "giriş alınabilir mi kısa yorum",
  "invalidation": "bu fikir hangi durumda bozulur",
  "news_effect": "POZITIF|NEGATIF|NOTR|HABER_YOK",
  "final_note": "kısa Türkçe not"
}
"""


def build_ai_user_prompt(
    symbol: str,
    tech: TechnicalSnapshot,
    flow: FlowSnapshot,
    der: DerivativesSnapshot,
    deterministic: Dict[str, Any],
    external: Dict[str, Any],
    existing_payload: Optional[Dict[str, Any]] = None,
) -> str:
    payload_text = ""
    if existing_payload:
        # Ana botun kararını da ver, ama AI kör onaylamasın.
        safe_payload = {
            "stage": existing_payload.get("stage"),
            "signal_label": existing_payload.get("signal_label"),
            "side": existing_payload.get("side") or existing_payload.get("direction"),
            "score": existing_payload.get("score"),
            "quality": existing_payload.get("quality") or existing_payload.get("quality_score"),
            "entry": existing_payload.get("entry") or existing_payload.get("price"),
            "stop": existing_payload.get("stop"),
            "tp1": existing_payload.get("tp1"),
            "tp2": existing_payload.get("tp2"),
            "tp3": existing_payload.get("tp3"),
            "reason": str(existing_payload.get("reason", ""))[:600],
        }
        payload_text = json_dumps_compact(safe_payload)

    news_items = external.get("items") or []
    compact_news = []
    for item in news_items[:8]:
        compact_news.append({
            "source": item.get("source"),
            "title": item.get("title"),
            "published_at": item.get("published_at"),
            "snippet": (item.get("snippet") or "")[:180],
        })

    return f"""
Coin: {symbol}
Türkiye saati: {tr_now_str()}

ANA BOT PAYLOAD:
{payload_text or "yok / research modu"}

TEKNİK SNAPSHOT:
{json_dumps_compact(asdict(tech))}

ORDER FLOW SNAPSHOT:
{json_dumps_compact(asdict(flow))}

OI/FUNDING SNAPSHOT:
{json_dumps_compact(asdict(der))}

SAYISAL YÖN SKORU:
{json_dumps_compact(deterministic)}

DIŞ ARAŞTIRMA / HABER:
Kaynaklar: {json_dumps_compact(external.get("enabled_sources", {}))}
Başlıklar: {json_dumps_compact(compact_news) if compact_news else "haber_yok"}

Senden istenen:
Bu coin kısa vadede düşecek mi çıkacak mı? Eğer gerçekten işlem kalitesi varsa LONG_AL veya SHORT_AL ver.
Emin değilsen NO_SIGNAL ver. Ama kullanıcıya NO_SIGNAL yazdırılmayacak, sadece içeride kalacak.
"""


# ============================================================
# ANA PROFESYONEL AI SINIFI
# ============================================================

class ProfessionalCryptoAI:
    def __init__(self):
        self.http = HTTPClient()
        self.okx = OKXResearchData(self.http)
        self.external = ExternalResearchEngine(self.http)
        self.brain = DeepSeekResearchBrain(self.http)
        self.history = deque(maxlen=800)
        self.stats = {
            "research_count": 0,
            "long_al": 0,
            "short_al": 0,
            "silent": 0,
            "ai_error": 0,
            "last_error": "",
        }

    async def close(self) -> None:
        await self.http.close()

    async def deep_research(
        self,
        symbol: str,
        existing_payload: Optional[Dict[str, Any]] = None,
        k1: Optional[List[List[Any]]] = None,
        k5: Optional[List[List[Any]]] = None,
        k15: Optional[List[List[Any]]] = None,
        k1h: Optional[List[List[Any]]] = None,
        k4h: Optional[List[List[Any]]] = None,
        orderbook: Optional[Dict[str, Any]] = None,
        trades: Optional[List[Dict[str, Any]]] = None,
        include_external: bool = True,
    ) -> Dict[str, Any]:
        symbol = normalize_symbol(symbol)

        # Dışarıdan veri gelmediyse OKX'ten toplar.
        market_pack: Dict[str, Any]
        if any([k1, k5, k15, k1h, k4h, orderbook, trades]):
            market_pack = {
                "symbol": symbol,
                "k1": k1 or [],
                "k5": k5 or [],
                "k15": k15 or [],
                "k1h": k1h or [],
                "k4h": k4h or [],
                "book": orderbook or {},
                "trades": trades or [],
                "ticker": {"last": (existing_payload or {}).get("price") or (existing_payload or {}).get("entry") or 0},
                "funding": {},
                "oi": {},
            }
            # Eksik temel veri varsa tamamla
            if not market_pack["k1"] or not market_pack["k5"] or not market_pack["k15"]:
                fetched = await self.okx.collect_market_pack(symbol)
                for key, val in fetched.items():
                    if not market_pack.get(key):
                        market_pack[key] = val
        else:
            market_pack = await self.okx.collect_market_pack(symbol)

        # Funding/OI dışarıdan payload ile gelmediyse OKX pack'te var.
        try:
            tech = tf_summary_from_klines(symbol, market_pack)
            flow = flow_snapshot(market_pack)
            der = derivatives_snapshot(market_pack)
            deterministic = deterministic_direction_score(tech, flow, der)
        except Exception as e:
            self.stats["ai_error"] += 1
            self.stats["last_error"] = f"snapshot hata: {str(e)[:120]}"
            return self._safe_no_signal(symbol, f"snapshot hata: {e}")

        external = {"items": [], "enabled_sources": {}}
        if include_external:
            try:
                max_news_items = PRO_AI_SIGNAL_NEWS_MAX_ITEMS if existing_payload else 15
                timeout_news = PRO_AI_SIGNAL_NEWS_TIMEOUT_SEC if existing_payload else 5.0
                external = await asyncio.wait_for(self.external.collect(symbol, max_items=max_news_items), timeout=timeout_news)
            except Exception as e:
                external = {"items": [], "enabled_sources": {}, "error": str(e)[:120]}

        prompt = build_ai_user_prompt(symbol, tech, flow, der, deterministic, external, existing_payload)

        ai_result = await self.brain.ask_json(PRO_SYSTEM_PROMPT, prompt, timeout_sec=PRO_AI_TIMEOUT_SEC)
        if not ai_result.get("success"):
            self.stats["ai_error"] += 1
            self.stats["last_error"] = ai_result.get("error", "")
            if PRO_AI_FAIL_OPEN and existing_payload:
                # Fail-open açıksa ana bot sinyalini bozmaz, ama AI onayı saymaz.
                return {
                    "symbol": symbol,
                    "action": self._action_from_payload(existing_payload),
                    "direction": self._direction_from_payload(existing_payload),
                    "confidence": 0,
                    "signal_score": safe_float(existing_payload.get("score"), 0),
                    "risk": 50,
                    "market_regime": "AI_HATA_ANA_SINYAL_KORUNDU",
                    "research_summary": "AI çalışmadı, ana bot sinyali korundu.",
                    "main_reasons": deterministic.get("notes", [])[:3],
                    "danger_flags": deterministic.get("risk_flags", []),
                    "entry_comment": "Ana bot seviyesi korunur.",
                    "invalidation": "",
                    "news_effect": "HABER_YOK",
                    "final_note": "",
                    "send_signal": True,
                    "tech": asdict(tech),
                    "flow": asdict(flow),
                    "derivatives": asdict(der),
                    "deterministic": deterministic,
                    "external_count": len(external.get("items") or []),
                    "ai_error": ai_result.get("error", ""),
                }
            return self._safe_no_signal(symbol, ai_result.get("error", "AI hata"), tech, flow, der, deterministic, external)

        verdict = self._sanitize_ai_verdict(symbol, ai_result.get("parsed") or {}, tech, flow, der, deterministic, external)
        self.stats["research_count"] += 1
        self.history.append({
            "ts": now_ts(),
            "symbol": symbol,
            "action": verdict.get("action"),
            "direction": verdict.get("direction"),
            "confidence": verdict.get("confidence"),
            "score": verdict.get("signal_score"),
            "risk": verdict.get("risk"),
        })

        return verdict

    def _safe_no_signal(
        self,
        symbol: str,
        reason: str,
        tech: Optional[TechnicalSnapshot] = None,
        flow: Optional[FlowSnapshot] = None,
        der: Optional[DerivativesSnapshot] = None,
        deterministic: Optional[Dict[str, Any]] = None,
        external: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self.stats["silent"] += 1
        return {
            "symbol": normalize_symbol(symbol),
            "action": "NO_SIGNAL",
            "direction": "RANGE",
            "confidence": 0,
            "signal_score": 0,
            "risk": 100,
            "market_regime": "KARISIK",
            "research_summary": reason[:200],
            "main_reasons": [],
            "danger_flags": [reason[:120]],
            "entry_comment": "",
            "invalidation": "",
            "news_effect": "HABER_YOK",
            "final_note": "",
            "send_signal": False,
            "tech": asdict(tech) if tech else {},
            "flow": asdict(flow) if flow else {},
            "derivatives": asdict(der) if der else {},
            "deterministic": deterministic or {},
            "external_count": len((external or {}).get("items") or []),
        }

    def _action_from_payload(self, payload: Dict[str, Any]) -> str:
        text = " ".join(str(payload.get(k, "")) for k in ("signal_label", "side", "direction", "reason")).upper()
        if "LONG" in text:
            return "LONG_AL"
        if "SHORT" in text:
            return "SHORT_AL"
        return "NO_SIGNAL"

    def _direction_from_payload(self, payload: Dict[str, Any]) -> str:
        action = self._action_from_payload(payload)
        if action == "LONG_AL":
            return "YUKARI"
        if action == "SHORT_AL":
            return "AŞAĞI"
        return "RANGE"

    def _sanitize_ai_verdict(
        self,
        symbol: str,
        raw: Dict[str, Any],
        tech: TechnicalSnapshot,
        flow: FlowSnapshot,
        der: DerivativesSnapshot,
        deterministic: Dict[str, Any],
        external: Dict[str, Any],
    ) -> Dict[str, Any]:
        action = str(raw.get("action", "NO_SIGNAL")).upper().strip()
        if action not in ("LONG_AL", "SHORT_AL", "NO_SIGNAL"):
            action = "NO_SIGNAL"

        direction = str(raw.get("direction", "RANGE")).upper().strip()
        if direction not in ("YUKARI", "AŞAĞI", "RANGE"):
            direction = "RANGE"

        confidence = max(0.0, min(100.0, safe_float(raw.get("confidence"), 0)))
        signal_score = max(0.0, min(100.0, safe_float(raw.get("signal_score"), 0)))
        risk = max(0.0, min(100.0, safe_float(raw.get("risk"), 100)))
        market_regime = str(raw.get("market_regime", "KARISIK")).upper().strip()[:80]
        news_effect = str(raw.get("news_effect", "HABER_YOK")).upper().strip()[:40]

        main_reasons = raw.get("main_reasons") or []
        if not isinstance(main_reasons, list):
            main_reasons = [str(main_reasons)]
        main_reasons = [str(x)[:180] for x in main_reasons[:5]]

        danger_flags = raw.get("danger_flags") or []
        if not isinstance(danger_flags, list):
            danger_flags = [str(danger_flags)]
        danger_flags = [str(x)[:180] for x in danger_flags[:5]]

        # Katı güven kapısı. Dışarıya etiket yok, sadece sinyali susturur.
        send_signal = action in ("LONG_AL", "SHORT_AL")
        if confidence < PRO_AI_MIN_CONFIDENCE or signal_score < PRO_AI_MIN_SIGNAL_SCORE:
            send_signal = False
            action = "NO_SIGNAL"

        # Yön-tutarlılık kapısı
        if action == "SHORT_AL" and direction != "AŞAĞI":
            send_signal = False
            action = "NO_SIGNAL"
        if action == "LONG_AL" and direction != "YUKARI":
            send_signal = False
            action = "NO_SIGNAL"

        # AI yön otomatik sinyal köprüsü.
        # Model "NO_SIGNAL" dese bile yön/edge/akış/risk güçlü ise bunu otomatik AL mesajına bağlar.
        # Bu köprü AAVE gibi "aşağı eğilim var ama ana bot sinyal üretmedi" boşluğunu kapatmak için eklendi.
        if PRO_AI_DIRECTION_AUTO_SIGNAL_ENABLED and action == "NO_SIGNAL" and direction in ("AŞAĞI", "YUKARI"):
            det_long = safe_float(deterministic.get("long_score"), 0)
            det_short = safe_float(deterministic.get("short_score"), 0)
            edge = safe_float(deterministic.get("edge"), abs(det_long - det_short))

            conf_need = PRO_AI_DIRECTION_MIN_CONFIDENCE
            score_need = PRO_AI_DIRECTION_MIN_SIGNAL_SCORE
            if (direction == "AŞAĞI" and news_effect == "NEGATIF") or (direction == "YUKARI" and news_effect == "POZITIF"):
                conf_need = max(50.0, conf_need - 4.0)
                score_need = max(45.0, score_need - 4.0)
            if (direction == "AŞAĞI" and "DUSUS" in market_regime) or (direction == "YUKARI" and "PUMP" in market_regime):
                conf_need = max(50.0, conf_need - 2.0)
                score_need = max(45.0, score_need - 2.0)

            base_ok = (
                confidence >= conf_need
                and signal_score >= score_need
                and risk <= PRO_AI_DIRECTION_MAX_RISK
                and edge >= PRO_AI_DIRECTION_MIN_EDGE
            )
            short_context_ok = (
                direction == "AŞAĞI"
                and det_short >= det_long + PRO_AI_DIRECTION_MIN_EDGE
                and flow.flow_direction == "SATIŞ_BASKIN"
                and flow.sell_buy_ratio >= PRO_AI_DIRECTION_MIN_FLOW_RATIO
                and tech.ema_state_1m not in ("GÜÇLÜ_YUKARI", "YUKARI_EĞİLİM")
                and tech.ema_state_5m not in ("GÜÇLÜ_YUKARI",)
                and tech.drop_from_peak_pct <= PRO_AI_DIRECTION_MAX_SHORT_DROP_FROM_PEAK_PCT
            )
            long_context_ok = (
                direction == "YUKARI"
                and det_long >= det_short + PRO_AI_DIRECTION_MIN_EDGE
                and flow.flow_direction == "ALIŞ_BASKIN"
                and flow.buy_sell_ratio >= PRO_AI_DIRECTION_MIN_FLOW_RATIO
                and tech.ema_state_1m not in ("GÜÇLÜ_AŞAĞI", "AŞAĞI_EĞİLİM")
                and tech.ema_state_5m not in ("GÜÇLÜ_AŞAĞI",)
            )

            if base_ok and short_context_ok:
                action = "SHORT_AL"
                send_signal = True
                main_reasons.insert(0, f"AI yön otomatik sinyale bağlandı: aşağı edge {edge:.1f}, satış akışı x{flow.sell_buy_ratio:.2f}")
            elif base_ok and long_context_ok:
                action = "LONG_AL"
                send_signal = True
                main_reasons.insert(0, f"AI yön otomatik sinyale bağlandı: yukarı edge {edge:.1f}, alış akışı x{flow.buy_sell_ratio:.2f}")

        # Basit güvenlik kapıları: AI çok güzel konuşsa da bariz çelişkileri engelle.
        if action == "SHORT_AL":
            if flow.flow_direction == "ALIŞ_BASKIN" and flow.buy_sell_ratio >= 1.8 and tech.ema_state_5m in ("GÜÇLÜ_YUKARI", "YUKARI_EĞİLİM"):
                send_signal = False
                action = "NO_SIGNAL"
                danger_flags.append("Alıcı akışı ve 5m trend short aleyhine güçlü.")
            if tech.drop_from_peak_pct > 2.5 and flow.flow_direction != "SATIŞ_BASKIN":
                send_signal = False
                action = "NO_SIGNAL"
                danger_flags.append("Düşüş kaçmış, short geç kalma riski yüksek.")

        if action == "LONG_AL":
            if flow.flow_direction == "SATIŞ_BASKIN" and flow.sell_buy_ratio >= 1.8 and tech.ema_state_5m in ("GÜÇLÜ_AŞAĞI", "AŞAĞI_EĞİLİM"):
                send_signal = False
                action = "NO_SIGNAL"
                danger_flags.append("Satıcı akışı ve 5m trend long aleyhine güçlü.")

        if not send_signal:
            self.stats["silent"] += 1
        elif action == "LONG_AL":
            self.stats["long_al"] += 1
        elif action == "SHORT_AL":
            self.stats["short_al"] += 1

        direction_for_levels = "SHORT" if action == "SHORT_AL" else "LONG" if action == "LONG_AL" else "NONE"
        levels = build_trade_levels(symbol, direction_for_levels, tech.price, tech)

        return {
            "symbol": symbol,
            "action": action,
            "direction": direction,
            "confidence": round(confidence, 1),
            "signal_score": round(signal_score, 1),
            "risk": round(risk, 1),
            "market_regime": market_regime,
            "research_summary": str(raw.get("research_summary", ""))[:500],
            "main_reasons": main_reasons,
            "danger_flags": danger_flags,
            "entry_comment": str(raw.get("entry_comment", ""))[:300],
            "invalidation": str(raw.get("invalidation", ""))[:300],
            "news_effect": news_effect,
            "final_note": str(raw.get("final_note", ""))[:300],
            "send_signal": bool(send_signal),
            "levels": levels,
            "tech": asdict(tech),
            "flow": asdict(flow),
            "derivatives": asdict(der),
            "deterministic": deterministic,
            "external_count": len(external.get("items") or []),
        }


# ============================================================
# SİNYAL MESAJI / RAPOR FORMATLARI
# ============================================================

def build_ai_signal_message(verdict: Dict[str, Any]) -> str:
    """
    Sadece gerçek AL varsa mesaj üretir.
    NO_SIGNAL durumunda boş string döner.
    """
    if not verdict or not verdict.get("send_signal"):
        return ""

    action = verdict.get("action")
    if action not in ("LONG_AL", "SHORT_AL"):
        return ""

    symbol = verdict.get("symbol", "?")
    levels = verdict.get("levels") or {}
    tech = verdict.get("tech") or {}
    flow = verdict.get("flow") or {}

    side = "LONG AL" if action == "LONG_AL" else "SHORT AL"
    emoji = "🟢" if action == "LONG_AL" else "🔴"

    reasons = verdict.get("main_reasons") or []
    reason_text = "\n".join(f"• {r}" for r in reasons[:3]) if reasons else "• Piyasa yapısı ve akış uygun."

    msg = f"{emoji} {side}\n"
    msg += f"⏰ Saat: {tr_now_str()}\n"
    msg += f"🎯 Coin: {symbol}\n"
    msg += f"📊 Güven: %{verdict.get('confidence', 0)} | Skor: {verdict.get('signal_score', 0)} | Risk: %{verdict.get('risk', 0)}\n"
    msg += f"🧭 Yön: {verdict.get('direction', '?')} | Rejim: {verdict.get('market_regime', '-')}\n"
    msg += f"💰 Giriş: {fmt_num(levels.get('entry', tech.get('price', 0)))}\n"
    msg += f"🛑 Stop: {fmt_num(levels.get('stop', 0))}\n"
    msg += f"🎯 TP1: {fmt_num(levels.get('tp1', 0))} | TP2: {fmt_num(levels.get('tp2', 0))} | TP3: {fmt_num(levels.get('tp3', 0))}\n"
    msg += f"📈 Pump 20m/1s: %{tech.get('change_20m', 0)} / %{tech.get('change_1h', 0)}\n"
    msg += f"📉 RSI 1/5/15: {tech.get('rsi_1m', 0)} / {tech.get('rsi_5m', 0)} / {tech.get('rsi_15m', 0)}\n"
    msg += f"🧲 Akış: {flow.get('flow_direction', '-')} | Sell/Buy: x{flow.get('sell_buy_ratio', 0)} | Buy/Sell: x{flow.get('buy_sell_ratio', 0)}\n"
    msg += f"\n🧠 Sebep:\n{reason_text}\n"

    if verdict.get("entry_comment"):
        msg += f"\n📝 Not: {verdict.get('entry_comment')}\n"
    if verdict.get("invalidation"):
        msg += f"⚠️ Bozulma: {verdict.get('invalidation')}\n"

    return msg.strip()


def build_research_report(verdict: Dict[str, Any]) -> str:
    """
    Komutla çağrıldığında yön araştırma raporu.
    Bu otomatik sinyal değildir; kullanıcı istediğinde analiz verir.
    """
    if not verdict:
        return "Araştırma sonucu alınamadı."

    symbol = verdict.get("symbol", "?")
    tech = verdict.get("tech") or {}
    flow = verdict.get("flow") or {}
    der = verdict.get("derivatives") or {}
    det = verdict.get("deterministic") or {}
    action = verdict.get("action")

    if action == "LONG_AL":
        sonuc = "YUKARI ihtimali daha güçlü; LONG AL kalitesi var."
    elif action == "SHORT_AL":
        sonuc = "AŞAĞI ihtimali daha güçlü; SHORT AL kalitesi var."
    else:
        direction = verdict.get("direction", "RANGE")
        if direction == "YUKARI":
            sonuc = "Yukarı eğilim var ama AL kalitesi yeterince net değil."
        elif direction == "AŞAĞI":
            sonuc = "Aşağı eğilim var ama AL kalitesi yeterince net değil."
        else:
            sonuc = "Net yön yok; piyasa karışık/range."

    reasons = "\n".join(f"• {x}" for x in (verdict.get("main_reasons") or [])[:5]) or "• Net güçlü sebep yok."
    risks = "\n".join(f"• {x}" for x in (verdict.get("danger_flags") or [])[:5]) or "• Ek risk işareti yok."

    msg = f"🧠 PROFESYONEL KRİPTO AI ARAŞTIRMA\n"
    msg += f"⏰ {tr_now_str()}\n"
    msg += f"🎯 Coin: {symbol}\n\n"
    msg += f"📌 Sonuç: {sonuc}\n"
    msg += f"📊 Güven: %{verdict.get('confidence', 0)} | Sinyal Skoru: {verdict.get('signal_score', 0)} | Risk: %{verdict.get('risk', 0)}\n"
    msg += f"🧭 Yön: {verdict.get('direction', '?')} | Rejim: {verdict.get('market_regime', '-')}\n\n"
    msg += f"💰 Fiyat: {fmt_num(tech.get('price', 0))}\n"
    msg += f"📈 10m/20m/1s/4s: %{tech.get('change_10m', 0)} / %{tech.get('change_20m', 0)} / %{tech.get('change_1h', 0)} / %{tech.get('change_4h', 0)}\n"
    msg += f"📉 RSI 1/5/15: {tech.get('rsi_1m', 0)} / {tech.get('rsi_5m', 0)} / {tech.get('rsi_15m', 0)}\n"
    msg += f"🧱 EMA 1m/5m/15m: {tech.get('ema_state_1m', '-')} / {tech.get('ema_state_5m', '-')} / {tech.get('ema_state_15m', '-')}\n"
    msg += f"🧲 Akış: {flow.get('flow_direction', '-')} | Sell/Buy x{flow.get('sell_buy_ratio', 0)} | Buy/Sell x{flow.get('buy_sell_ratio', 0)}\n"
    msg += f"💸 Funding: %{der.get('funding_rate', 0)} | OI: {fmt_num(der.get('open_interest', 0))} {der.get('oi_currency', '')}\n"
    msg += f"⚖️ Sayısal skor Long/Short: {det.get('long_score', 0)} / {det.get('short_score', 0)} | Edge: {det.get('edge', 0)}\n"
    msg += f"📰 Haber kaynak sonucu: {verdict.get('news_effect', 'HABER_YOK')} | Başlık sayısı: {verdict.get('external_count', 0)}\n\n"
    msg += f"✅ Ana Nedenler:\n{reasons}\n\n"
    msg += f"⚠️ Riskler:\n{risks}\n\n"
    msg += f"📝 Özet: {verdict.get('research_summary', '-')}\n"
    if verdict.get("final_note"):
        msg += f"\nNot: {verdict.get('final_note')}"
    return msg[:3900]


# ============================================================
# MEVCUT BOTA ENTEGRASYON FONKSİYONLARI
# ============================================================

async def init_professional_crypto_ai() -> None:
    global professional_ai
    if professional_ai is None:
        professional_ai = ProfessionalCryptoAI()
        logger.info("🧠 Profesyonel Kripto AI başlatıldı. DeepSeek=%s", bool(DEEPSEEK_API_KEY))


async def shutdown_professional_crypto_ai() -> None:
    global professional_ai
    if professional_ai is not None:
        await professional_ai.close()
        professional_ai = None
        logger.info("🧠 Profesyonel Kripto AI kapatıldı.")


async def run_professional_ai_research(symbol: str, include_external: bool = True) -> Dict[str, Any]:
    if professional_ai is None:
        await init_professional_crypto_ai()
    assert professional_ai is not None
    include_external = bool(include_external and PRO_AI_EXTERNAL_RESEARCH_ON_COMMAND)
    return await professional_ai.deep_research(symbol, include_external=include_external)


async def run_professional_ai_on_payload(
    final_payload: Dict[str, Any],
    k1: Optional[List[List[Any]]] = None,
    k5: Optional[List[List[Any]]] = None,
    k15: Optional[List[List[Any]]] = None,
    k1h: Optional[List[List[Any]]] = None,
    k4h: Optional[List[List[Any]]] = None,
    orderbook: Optional[Dict[str, Any]] = None,
    trades: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Mevcut botun SIGNAL payload'ı üzerine derin AI araştırması uygular.
    Uygun değilse send_signal=False yapar; dışarıya red/bekle etiketi yazdırmaz.
    Uygunsa payload sinyal olarak kalır.
    """
    if not PRO_AI_ENABLED:
        return final_payload

    if professional_ai is None:
        await init_professional_crypto_ai()
    assert professional_ai is not None

    symbol = normalize_symbol(str(final_payload.get("symbol") or final_payload.get("coin") or ""))
    if not symbol:
        final_payload["send_signal"] = False
        return final_payload

    verdict = await professional_ai.deep_research(
        symbol=symbol,
        existing_payload=final_payload,
        k1=k1,
        k5=k5,
        k15=k15,
        k1h=k1h,
        k4h=k4h,
        orderbook=orderbook,
        trades=trades,
        include_external=PRO_AI_EXTERNAL_RESEARCH_ON_SIGNAL,
    )

    final_payload["professional_ai"] = verdict

    if not verdict.get("send_signal"):
        final_payload["send_signal"] = False
        # Dışarı görünmeyen sebep. Mesaja basma.
        final_payload["_internal_ai_silent_reason"] = verdict.get("research_summary", "")
        return final_payload

    # AI uygunsa ana bot sinyali korunur; sadece istenirse seviyeler eksikse tamamlanır.
    final_payload["send_signal"] = True
    levels = verdict.get("levels") or {}
    for k in ("entry", "stop", "tp1", "tp2", "tp3"):
        if final_payload.get(k) in (None, "", 0, "0") and levels.get(k):
            final_payload[k] = levels[k]

    return final_payload


# ============================================================
# TELEGRAM KOMUTLARI
# ============================================================

async def cmd_zeka(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not TELEGRAM_AVAILABLE:
        return
    if not context.args:
        await update.message.reply_text("Kullanım: /zeka BTC")
        return

    symbol = normalize_symbol(context.args[0])
    await update.message.reply_text(f"🧠 {symbol} derin araştırma yapılıyor...")

    try:
        verdict = await run_professional_ai_research(symbol, include_external=True)
        msg = build_research_report(verdict)
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"❌ Araştırma hatası: {str(e)[:180]}")


async def cmd_arastir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_zeka(update, context)


async def cmd_yon(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not TELEGRAM_AVAILABLE:
        return
    if not context.args:
        await update.message.reply_text("Kullanım: /yon BTC")
        return

    symbol = normalize_symbol(context.args[0])
    try:
        verdict = await run_professional_ai_research(symbol, include_external=False)
        report = build_research_report(verdict)
        await update.message.reply_text(report)
    except Exception as e:
        await update.message.reply_text(f"❌ Yön analizi hatası: {str(e)[:180]}")


async def cmd_ai_durum(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not TELEGRAM_AVAILABLE:
        return
    if professional_ai is None:
        await init_professional_crypto_ai()
    assert professional_ai is not None

    s = professional_ai.stats
    cache_http = professional_ai.http.cache.stats()
    cache_ai = professional_ai.brain.cache.stats()

    msg = "🧠 PROFESYONEL KRİPTO AI DURUM\n"
    msg += f"API: {'✅ Aktif' if DEEPSEEK_API_KEY else '❌ Key yok'}\n"
    msg += f"Model: {DEEPSEEK_MODEL}\n"
    msg += f"Araştırma: {s.get('research_count', 0)}\n"
    msg += f"LONG AL: {s.get('long_al', 0)} | SHORT AL: {s.get('short_al', 0)}\n"
    msg += f"Sessiz geçen: {s.get('silent', 0)} | AI hata: {s.get('ai_error', 0)}\n"
    msg += f"HTTP Cache: {cache_http.get('size')}/{cache_http.get('max_size')} | Hit %{cache_http.get('hit_rate')}\n"
    msg += f"AI Cache: {cache_ai.get('size')}/{cache_ai.get('max_size')} | Hit %{cache_ai.get('hit_rate')}\n"
    if s.get("last_error"):
        msg += f"Son hata: {s.get('last_error')[:160]}\n"
    await update.message.reply_text(msg)


def add_professional_ai_handlers(application: Any) -> None:
    if not TELEGRAM_AVAILABLE or CommandHandler is None:
        logger.warning("Telegram handler eklenemedi: python-telegram-bot yok.")
        return
    application.add_handler(CommandHandler("zeka", cmd_zeka))
    application.add_handler(CommandHandler("arastir", cmd_arastir))
    application.add_handler(CommandHandler("yon", cmd_yon))
    application.add_handler(CommandHandler("ai_durum", cmd_ai_durum))


# ============================================================
# CLI TEST
# ============================================================

async def _cli_main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Profesyonel Kripto AI araştırma testi")
    parser.add_argument("symbol", nargs="?", default="BTC", help="BTC / ETH / SOL gibi coin")
    parser.add_argument("--no-news", action="store_true", help="Dış haber araştırmasını kapat")
    args = parser.parse_args()

    await init_professional_crypto_ai()
    try:
        verdict = await run_professional_ai_research(args.symbol, include_external=not args.no_news)
        print(build_research_report(verdict))
        signal = build_ai_signal_message(verdict)
        if signal:
            print("\n--- SİNYAL MESAJI ---")
            print(signal)
    finally:
        await shutdown_professional_crypto_ai()


if __name__ == "__main__":
    asyncio.run(_cli_main())

'''
# Dataclass kullanan gömülü modülün güvenli yüklenmesi.
# Not: dataclasses, sınıfın __module__ değerini sys.modules içinde arar.
# Modül sys.modules'a eklenmezse Railway/Python 3.11 ortamında:
# "'NoneType' object has no attribute '__dict__'" hatası oluşabilir.
import sys as _pro_ai_sys
import types as _pro_ai_types
_PROFESSIONAL_AI_MODULE_NAME = "_embedded_professional_crypto_ai"
_PROFESSIONAL_AI_MODULE = _pro_ai_types.ModuleType(_PROFESSIONAL_AI_MODULE_NAME)
_PROFESSIONAL_AI_MODULE.__file__ = "<embedded_professional_crypto_ai>"
_PROFESSIONAL_AI_NS: Dict[str, Any] = _PROFESSIONAL_AI_MODULE.__dict__
_PROFESSIONAL_AI_NS["__name__"] = _PROFESSIONAL_AI_MODULE_NAME
_PROFESSIONAL_AI_NS["__file__"] = "<embedded_professional_crypto_ai>"
_pro_ai_sys.modules[_PROFESSIONAL_AI_MODULE_NAME] = _PROFESSIONAL_AI_MODULE

PROFESSIONAL_AI_AVAILABLE = False
PROFESSIONAL_AI_LOAD_ERROR = ""
try:
    exec(_PROFESSIONAL_AI_CODE, _PROFESSIONAL_AI_NS)
    PROFESSIONAL_AI_AVAILABLE = True
    logger.info("Profesyonel Kripto AI modülü yüklendi")
except Exception as _pro_ai_load_exc:
    PROFESSIONAL_AI_AVAILABLE = False
    PROFESSIONAL_AI_LOAD_ERROR = str(_pro_ai_load_exc)[:220]
    logger.warning("Profesyonel Kripto AI yüklenemedi: %s", PROFESSIONAL_AI_LOAD_ERROR)


def professional_ai_enabled() -> bool:
    if not PROFESSIONAL_AI_AVAILABLE:
        return False
    return bool(_PROFESSIONAL_AI_NS.get("PRO_AI_ENABLED", False))


def professional_ai_fail_open() -> bool:
    if not PROFESSIONAL_AI_AVAILABLE:
        return True
    return bool(_PROFESSIONAL_AI_NS.get("PRO_AI_FAIL_OPEN", False))


async def init_professional_crypto_ai_embedded() -> None:
    if not PROFESSIONAL_AI_AVAILABLE:
        logger.warning("Profesyonel AI pasif: %s", PROFESSIONAL_AI_LOAD_ERROR or "modül yok")
        return
    fn = _PROFESSIONAL_AI_NS.get("init_professional_crypto_ai")
    if fn:
        await fn()


async def shutdown_professional_crypto_ai_embedded() -> None:
    if not PROFESSIONAL_AI_AVAILABLE:
        return
    fn = _PROFESSIONAL_AI_NS.get("shutdown_professional_crypto_ai")
    if fn:
        await fn()


async def run_professional_ai_on_payload_embedded(res: Dict[str, Any]) -> Dict[str, Any]:
    if not professional_ai_enabled():
        return res
    fn = _PROFESSIONAL_AI_NS.get("run_professional_ai_on_payload")
    if not fn:
        return res
    return await fn(res)


def add_professional_ai_handlers_embedded(application: Any) -> None:
    if not PROFESSIONAL_AI_AVAILABLE:
        logger.warning("Profesyonel AI handler eklenmedi: %s", PROFESSIONAL_AI_LOAD_ERROR or "modül yok")
        return
    fn = _PROFESSIONAL_AI_NS.get("add_professional_ai_handlers")
    if fn:
        try:
            fn(application)
            logger.info("Profesyonel AI komutları eklendi: /zeka /arastir /yon /ai_durum")
        except Exception as e:
            logger.warning("Profesyonel AI handler ekleme hatası: %s", str(e)[:160])


def professional_ai_status_line() -> str:
    if not PROFESSIONAL_AI_AVAILABLE:
        return "🧠 Profesyonel AI: ❌ " + (PROFESSIONAL_AI_LOAD_ERROR or "yüklenmedi")
    key_ok = bool(_PROFESSIONAL_AI_NS.get("DEEPSEEK_API_KEY", ""))
    enabled = bool(_PROFESSIONAL_AI_NS.get("PRO_AI_ENABLED", False))
    return "🧠 Profesyonel AI: " + ("✅ Aktif" if enabled else "⚪ Kapalı") + " | DeepSeek: " + ("✅" if key_ok else "❌ Key yok")



async def cmd_ai_durum_direct(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ana bot seviyesinde garanti /ai_durum cevabı.
    Embedded AI handler eklenemese bile kullanıcı sessiz kalmasın diye burada doğrudan yanıt verir.
    """
    try:
        if not PROFESSIONAL_AI_AVAILABLE:
            await update.message.reply_text(
                "🧠 PROFESYONEL KRİPTO AI DURUM\n"
                f"Durum: ❌ Yüklenemedi\n"
                f"Hata: {PROFESSIONAL_AI_LOAD_ERROR or 'Bilinmeyen yükleme hatası'}\n"
                "Not: Bu cevap geldiyse /ai_durum komutu artık bağlı; sorun AI modülünün yüklenmesindedir."
            )
            return

        await init_professional_crypto_ai_embedded()
        ai_obj = _PROFESSIONAL_AI_NS.get("professional_ai")
        api_key = _PROFESSIONAL_AI_NS.get("DEEPSEEK_API_KEY", "")
        model = _PROFESSIONAL_AI_NS.get("DEEPSEEK_MODEL", "deepseek-chat")
        enabled = bool(_PROFESSIONAL_AI_NS.get("PRO_AI_ENABLED", False))

        msg = "🧠 PROFESYONEL KRİPTO AI DURUM\n"
        msg += f"Modül: {'✅ Yüklü' if PROFESSIONAL_AI_AVAILABLE else '❌ Yok'}\n"
        msg += f"AI açık: {'✅ Evet' if enabled else '⚪ Hayır'}\n"
        msg += f"DeepSeek key: {'✅ Var' if api_key else '❌ Yok'}\n"
        msg += f"Model: {model}\n"
        try:
            msg += f"Google News RSS: {'✅ Açık' if _PROFESSIONAL_AI_NS.get('GOOGLE_NEWS_RSS_ENABLED', False) else '⚪ Kapalı'}\n"
            msg += f"Haber/Sinyal: {'✅ Açık' if _PROFESSIONAL_AI_NS.get('PRO_AI_EXTERNAL_RESEARCH_ON_SIGNAL', False) else '⚪ Kapalı'} | Haber/Komut: {'✅ Açık' if _PROFESSIONAL_AI_NS.get('PRO_AI_EXTERNAL_RESEARCH_ON_COMMAND', False) else '⚪ Kapalı'}\n"
        except Exception:
            pass

        if ai_obj is not None:
            s = getattr(ai_obj, 'stats', {}) or {}
            msg += f"Araştırma: {s.get('research_count', 0)}\n"
            msg += f"LONG AL: {s.get('long_al', 0)} | SHORT AL: {s.get('short_al', 0)}\n"
            msg += f"Sessiz: {s.get('silent', 0)} | AI hata: {s.get('ai_error', 0)}\n"
            last_error = s.get('last_error', '')
            if last_error:
                msg += f"Son hata: {str(last_error)[:160]}\n"
            try:
                http_cache = ai_obj.http.cache.stats()
                ai_cache = ai_obj.brain.cache.stats()
                msg += f"HTTP Cache: {http_cache.get('size', 0)}/{http_cache.get('max_size', 0)} | Hit %{http_cache.get('hit_rate', 0)}\n"
                msg += f"AI Cache: {ai_cache.get('size', 0)}/{ai_cache.get('max_size', 0)} | Hit %{ai_cache.get('hit_rate', 0)}\n"
            except Exception:
                pass
        else:
            msg += "AI nesnesi: ⚠️ Başlatılamadı\n"

        msg += "\nKomutlar: /zeka BTC | /arastir BTC | /yon BTC"
        await update.message.reply_text(msg[:3900])
    except Exception as e:
        await update.message.reply_text(f"❌ /ai_durum hata: {str(e)[:220]}")


async def cmd_zeka_direct(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        if not context.args:
            await update.message.reply_text("Kullanım: /zeka BTC")
            return
        if not PROFESSIONAL_AI_AVAILABLE:
            await update.message.reply_text("❌ Profesyonel AI yüklenemedi: " + (PROFESSIONAL_AI_LOAD_ERROR or "bilinmeyen hata"))
            return
        symbol = context.args[0].upper().strip()
        await update.message.reply_text(f"🧠 {symbol} derin araştırma yapılıyor...")
        await init_professional_crypto_ai_embedded()
        research_fn = _PROFESSIONAL_AI_NS.get("run_professional_ai_research")
        report_fn = _PROFESSIONAL_AI_NS.get("build_research_report")
        if not research_fn or not report_fn:
            await update.message.reply_text("❌ Profesyonel AI araştırma fonksiyonu bulunamadı.")
            return
        verdict = await research_fn(symbol, include_external=True)
        msg = report_fn(verdict)
        await update.message.reply_text(str(msg)[:3900])
    except Exception as e:
        await update.message.reply_text(f"❌ /zeka hata: {str(e)[:220]}")


async def cmd_arastir_direct(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_zeka_direct(update, context)


async def cmd_yon_direct(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        if not context.args:
            await update.message.reply_text("Kullanım: /yon BTC")
            return
        if not PROFESSIONAL_AI_AVAILABLE:
            await update.message.reply_text("❌ Profesyonel AI yüklenemedi: " + (PROFESSIONAL_AI_LOAD_ERROR or "bilinmeyen hata"))
            return
        symbol = context.args[0].upper().strip()
        await update.message.reply_text(f"🧭 {symbol} yön analizi yapılıyor...")
        await init_professional_crypto_ai_embedded()
        research_fn = _PROFESSIONAL_AI_NS.get("run_professional_ai_research")
        report_fn = _PROFESSIONAL_AI_NS.get("build_research_report")
        if not research_fn or not report_fn:
            await update.message.reply_text("❌ Profesyonel AI yön fonksiyonu bulunamadı.")
            return
        verdict = await research_fn(symbol, include_external=False)
        msg = report_fn(verdict)
        await update.message.reply_text(str(msg)[:3900])
    except Exception as e:
        await update.message.reply_text(f"❌ /yon hata: {str(e)[:220]}")


def _ai_verdict_action_to_direction(action: str) -> str:
    action = str(action or "").upper()
    if action == "LONG_AL":
        return "LONG"
    if action == "SHORT_AL":
        return "SHORT"
    return ""


def _calc_rr_from_levels(direction: str, entry: float, stop: float, tp1: float) -> float:
    risk = abs(stop - entry)
    reward = abs(entry - tp1)
    if risk <= 0:
        return 0.0
    return round(reward / risk, 2)



def _ai_auto_extract_numbers(payload: Dict[str, Any]) -> Dict[str, float]:
    """
    AI otomatik payload içinden final kapı sayıları.
    Tek kaynak yoksa professional_ai/deterministic/tech/flow alanlarından tamamlar.
    """
    verdict = payload.get("professional_ai") if isinstance(payload.get("professional_ai"), dict) else {}
    det = verdict.get("deterministic") if isinstance(verdict.get("deterministic"), dict) else {}
    tech = verdict.get("tech") if isinstance(verdict.get("tech"), dict) else {}
    flow = verdict.get("flow") if isinstance(verdict.get("flow"), dict) else {}
    payload_flow = payload.get("trade_flow") if isinstance(payload.get("trade_flow"), dict) else {}

    direction = str(payload.get("direction") or _ai_verdict_action_to_direction(str(verdict.get("action", ""))) or "SHORT").upper()

    long_score = safe_float(det.get("long_score"), 0)
    short_score = safe_float(det.get("short_score"), 0)
    raw_edge = safe_float(det.get("edge"), abs(long_score - short_score))
    edge = raw_edge
    if direction == "LONG" and long_score > 0:
        edge = long_score - short_score
    elif direction == "SHORT" and short_score > 0:
        edge = short_score - long_score

    return {
        "confidence": safe_float(payload.get("ai_confidence", verdict.get("confidence", 0)), 0),
        "signal_score": safe_float(payload.get("ai_signal_score", verdict.get("signal_score", payload.get("breakdown_score", 0))), 0),
        "risk": safe_float(payload.get("ai_risk", verdict.get("risk", 100)), 100),
        "edge": safe_float(payload.get("ai_edge", edge), 0),
        "long_score": long_score,
        "short_score": short_score,
        "rr": safe_float(payload.get("rr"), 0),
        "rsi1": safe_float(payload.get("rsi1", tech.get("rsi_1m", 50)), 50),
        "rsi5": safe_float(payload.get("rsi5", tech.get("rsi_5m", 50)), 50),
        "rsi15": safe_float(payload.get("rsi15", tech.get("rsi_15m", 50)), 50),
        "change_10m": safe_float(tech.get("change_10m", payload.get("pump_10m", 0)), 0),
        "change_20m": safe_float(tech.get("change_20m", payload.get("pump_20m", 0)), 0),
        "change_1h": safe_float(tech.get("change_1h", payload.get("pump_1h", 0)), 0),
        "pump_context": safe_float(tech.get("pump_context", 0), 0),
        "near_peak_pct": safe_float(tech.get("near_peak_pct", 999), 999),
        "drop_from_peak_pct": safe_float(tech.get("drop_from_peak_pct", 999), 999),
        "vol1": safe_float(payload.get("vol_ratio_1m", tech.get("volume_1m_mult", 0)), 0),
        "vol5": safe_float(payload.get("vol_ratio_5m", tech.get("volume_5m_mult", 0)), 0),
        "sell_buy": safe_float(flow.get("sell_buy_ratio", payload_flow.get("sell_to_buy", 0)), 0),
        "buy_sell": safe_float(flow.get("buy_sell_ratio", payload_flow.get("buy_to_sell", 0)), 0),
    }


def validate_ai_auto_final_gate(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """
    AI otomatik sinyalin gerçek gönderim kapısı.
    Amaç botu susturmak değil:
      - kötü/çok geç sinyali keser,
      - orta sinyali iç takipte bırakır,
      - güçlü ve doğru yerdeki sinyali geçirir.

    WOO tipi: edge düşük + risk yüksek + RSI aşırı satım -> BLOK.
    LRC tipi: düşüş bittikten sonra düşük RSI ile SHORT -> BLOK.
    Tepe bölgesi/ilk kırılım SHORT'ları korunur.
    """
    if not payload.get("ai_auto_promoted"):
        return True, "AI otomatik sinyal değil."

    direction = str(payload.get("direction", "SHORT")).upper()
    n = _ai_auto_extract_numbers(payload)

    conf = n["confidence"]
    score = n["signal_score"]
    risk = n["risk"]
    edge = n["edge"]
    rr = n["rr"]

    min_edge = PRO_AI_AUTOSIGNAL_LONG_MIN_EDGE if direction == "LONG" else PRO_AI_AUTOSIGNAL_SHORT_MIN_EDGE

    blocks: List[str] = []
    if conf < PRO_AI_AUTOSIGNAL_MIN_CONFIDENCE:
        blocks.append(f"güven düşük {conf:.1f}/{PRO_AI_AUTOSIGNAL_MIN_CONFIDENCE:.1f}")
    if score < PRO_AI_AUTOSIGNAL_MIN_SIGNAL_SCORE:
        blocks.append(f"skor düşük {score:.1f}/{PRO_AI_AUTOSIGNAL_MIN_SIGNAL_SCORE:.1f}")
    if risk > PRO_AI_AUTOSIGNAL_MAX_RISK:
        blocks.append(f"risk yüksek {risk:.1f}/{PRO_AI_AUTOSIGNAL_MAX_RISK:.1f}")
    if edge < min_edge:
        blocks.append(f"edge düşük {edge:.1f}/{min_edge:.1f}")
    if rr < PRO_AI_AUTOSIGNAL_MIN_RR:
        blocks.append(f"RR düşük {rr:.2f}/{PRO_AI_AUTOSIGNAL_MIN_RR:.2f}")

    if blocks:
        return False, "AI OTOMATİK FİNAL KAPI BLOK: " + " | ".join(blocks)

    # AI otomatik sinyal için Binance teyidi henüz bilinmeden yapılabilecek ONE tipi erken blok:
    # Pump zayıf + RSI1 düşükse ve veri içinde ters CVD görünüyorsa dış sinyal yok.
    if direction == "SHORT":
        pre_guard = short_context_guard_reason(payload, str(payload.get("binance_confirm_status", "")))
        if pre_guard:
            return False, "AI OTOMATİK SHORT CONTEXT BLOK: " + pre_guard

    if direction == "SHORT" and PRO_AI_AUTOSIGNAL_SHORT_LATE_FILTER_ENABLED:
        # Düşüş bittikten sonra short istemiyoruz.
        if n["rsi1"] <= PRO_AI_AUTOSIGNAL_SHORT_RSI1_OVERSOLD_BLOCK:
            return False, (
                f"AI OTOMATİK GEÇ SHORT BLOK: RSI1 aşırı satım {n['rsi1']:.1f}; "
                "düşüş bittikten sonra SHORT AL yok."
            )

        if (
            n["rsi5"] <= PRO_AI_AUTOSIGNAL_SHORT_RSI5_WEAK_BLOCK
            and n["rsi15"] <= PRO_AI_AUTOSIGNAL_SHORT_RSI15_WEAK_BLOCK
            and n["change_1h"] <= 0
        ):
            return False, (
                f"AI OTOMATİK GEÇ SHORT BLOK: RSI5/15 zayıf {n['rsi5']:.1f}/{n['rsi15']:.1f}, "
                f"1s hareket {n['change_1h']:.2f}; düşüşün gövdesi geçmiş."
            )

        has_top_context = (
            n["pump_context"] >= PRO_AI_AUTOSIGNAL_SHORT_MIN_PUMP_CONTEXT
            or n["change_20m"] >= PRO_AI_AUTOSIGNAL_SHORT_MIN_PUMP_CONTEXT
            or n["rsi15"] >= 58
            or n["near_peak_pct"] <= PRO_AI_AUTOSIGNAL_SHORT_MAX_NEAR_PEAK_PCT
        )
        if PRO_AI_AUTOSIGNAL_SHORT_MIN_TOP_CONTEXT and not has_top_context:
            return False, (
                "AI OTOMATİK GEÇ SHORT BLOK: tepe/pump bağlamı yok; "
                f"pump_context={n['pump_context']:.2f}, 20m={n['change_20m']:.2f}, "
                f"near_peak={n['near_peak_pct']:.2f}, RSI15={n['rsi15']:.1f}."
            )

    if direction == "LONG" and PRO_AI_AUTOSIGNAL_LONG_OVERHEAT_FILTER_ENABLED:
        # Tepede kovalamayı keser; trend devam longları tamamen öldürmez.
        if n["rsi1"] >= PRO_AI_AUTOSIGNAL_LONG_RSI1_OVERHEAT_BLOCK and n["rsi5"] >= PRO_AI_AUTOSIGNAL_LONG_RSI5_OVERHEAT_BLOCK:
            return False, (
                f"AI OTOMATİK GEÇ LONG BLOK: RSI1/5 aşırı ısınmış {n['rsi1']:.1f}/{n['rsi5']:.1f}; "
                "tepe kovalanmaz."
            )

    return True, (
        f"AI OTOMATİK FİNAL KAPI GEÇTİ: güven {conf:.1f}, skor {score:.1f}, "
        f"risk {risk:.1f}, edge {edge:.1f}/{min_edge:.1f}, RR {rr:.2f}"
    )



def build_ai_auto_signal_payload(symbol: str, verdict: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """AI araştırma sonucunu normal bot sinyal payload'ına çevirir.
    Dışarıya ayrı AI etiketi basılmaz; mesaj yine LONG AL / SHORT AL formatındadır.
    """
    if not verdict or not verdict.get("send_signal"):
        return None

    action = str(verdict.get("action", "")).upper()
    direction = _ai_verdict_action_to_direction(action)
    if direction not in ("LONG", "SHORT"):
        return None

    symbol = normalize_symbol(symbol or verdict.get("symbol", ""))
    levels = verdict.get("levels") if isinstance(verdict.get("levels"), dict) else {}
    tech = verdict.get("tech") if isinstance(verdict.get("tech"), dict) else {}
    flow = verdict.get("flow") if isinstance(verdict.get("flow"), dict) else {}
    det = verdict.get("deterministic") if isinstance(verdict.get("deterministic"), dict) else {}

    entry = safe_float(levels.get("entry"), safe_float(tech.get("price"), 0))
    stop = safe_float(levels.get("stop"), 0)
    tp1 = safe_float(levels.get("tp1"), 0)
    tp2 = safe_float(levels.get("tp2"), 0)
    tp3 = safe_float(levels.get("tp3"), 0)
    if entry <= 0 or stop <= 0 or tp1 <= 0:
        return None

    rr = _calc_rr_from_levels(direction, entry, stop, tp1)
    confidence = safe_float(verdict.get("confidence"), 0)
    signal_score = safe_float(verdict.get("signal_score"), 0)
    risk = safe_float(verdict.get("risk"), 100)
    total_score = round(max(signal_score, signal_score + confidence * 0.25 - risk * 0.10), 2)
    quality_score = round(clamp((confidence + signal_score - risk) / 12.0, 0.0, 10.0), 2)

    reasons = verdict.get("main_reasons") if isinstance(verdict.get("main_reasons"), list) else []
    reason_text = " | ".join(str(x) for x in reasons[:6]) if reasons else str(verdict.get("research_summary", "AI otomatik sinyal"))
    note = (
        f"AI OTOMATİK SİNYAL: {verdict.get('direction', '-')} | "
        f"Güven %{confidence:.1f} | Skor {signal_score:.1f} | Risk %{risk:.1f} | "
        f"Long/Short {det.get('long_score', 0)}/{det.get('short_score', 0)} edge={det.get('edge', 0)} | "
        f"{reason_text}"
    )

    payload = {
        "symbol": symbol,
        "direction": direction,
        "stage": "SIGNAL",
        "signal_label": "LONG AL" if direction == "LONG" else "SHORT AL",
        "score": total_score,
        "candidate_score": round(signal_score * 0.34, 2),
        "ready_score": round(signal_score * 0.33, 2),
        "verify_score": round(signal_score * 0.33, 2),
        "price": entry,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rr": rr,
        "pump_10m": safe_float(tech.get("change_10m"), 0),
        "pump_20m": safe_float(tech.get("change_20m"), 0),
        "pump_1h": safe_float(tech.get("change_1h"), 0),
        "drop_10m": round(-safe_float(tech.get("change_10m"), 0), 3),
        "drop_20m": round(-safe_float(tech.get("change_20m"), 0), 3),
        "drop_1h": round(-safe_float(tech.get("change_1h"), 0), 3),
        "rsi1": safe_float(tech.get("rsi_1m"), 0),
        "rsi5": safe_float(tech.get("rsi_5m"), 0),
        "rsi15": safe_float(tech.get("rsi_15m"), 0),
        "vol_ratio_1m": safe_float(tech.get("volume_1m_mult"), 0),
        "vol_ratio_5m": safe_float(tech.get("volume_5m_mult"), 0),
        "quote_volume": 0,
        "trend_guard_score": 0,
        "breakdown_score": signal_score,
        "green_streak": 0,
        "red_count_5": 0,
        "quality_score": quality_score,
        "quality_reason": "Profesyonel AI otomatik köprü",
        "reason": note[:1400],
        "ict": {},
        "long_close_gate": {},
        "trade_flow": flow,
        "orderbook": {},
        "whale_eye": {"enabled": True, "total_score": 0, "whale_confidence": "AI", "reason": "Profesyonel AI otomatik sinyal köprüsü"},
        "professional_ai": verdict,
        "professional_ai_checked": True,
        "ai_auto_promoted": True,
        "ai_confidence": confidence,
        "ai_signal_score": signal_score,
        "ai_risk": risk,
        "ai_edge": safe_float(det.get("edge"), abs(safe_float(det.get("long_score"), 0) - safe_float(det.get("short_score"), 0))),
        "ai_long_score": safe_float(det.get("long_score"), 0),
        "ai_short_score": safe_float(det.get("short_score"), 0),
        "invisible_class": "PROFESYONEL AI",
        "invisible_score": signal_score,
        "invisible_decision": "AI_OTOMATIK_SIGNAL",
    }

    gate_ok, gate_reason = validate_ai_auto_final_gate(payload)
    if not gate_ok:
        stats["ai_auto_final_block"] = stats.get("ai_auto_final_block", 0) + 1
        if direction == "SHORT" and "GEÇ SHORT" in gate_reason:
            stats["ai_auto_late_short_block"] = stats.get("ai_auto_late_short_block", 0) + 1
        if direction == "LONG" and "GEÇ LONG" in gate_reason:
            stats["ai_auto_late_long_block"] = stats.get("ai_auto_late_long_block", 0) + 1
        logger.info("AI otomatik final kapı blok %s %s: %s", direction, symbol, gate_reason)
        return None

    stats["ai_auto_final_pass"] = stats.get("ai_auto_final_pass", 0) + 1
    payload["reason"] = f"{payload.get('reason', '')} | {gate_reason}"[:1400]
    return payload


async def maybe_build_ai_auto_signal_for_symbol(symbol: str) -> Optional[Dict[str, Any]]:
    if not PRO_AI_AUTOSIGNAL_LOOP_ENABLED or not professional_ai_enabled():
        return None
    if not PROFESSIONAL_AI_AVAILABLE:
        return None
    symbol = normalize_symbol(symbol)
    if is_blocked_coin_symbol(symbol) or symbol_temporarily_blocked(symbol):
        return None
    now_ts = time.time()
    scan_mem = memory.setdefault("ai_auto_scan", {})
    rec = scan_mem.get(symbol, {}) if isinstance(scan_mem.get(symbol, {}), dict) else {}
    last_ts = safe_float(rec.get("last_ts", 0))
    if last_ts and now_ts - last_ts < PRO_AI_AUTOSIGNAL_PER_SYMBOL_COOLDOWN_SEC:
        return None
    # Aynı coin için yakın zamanda AI sinyali gittiyse pahalı AI araştırmasına bile girme.
    if ai_auto_recently_locked(symbol, "LONG") or ai_auto_recently_locked(symbol, "SHORT"):
        return None

    research_fn = _PROFESSIONAL_AI_NS.get("run_professional_ai_research")
    if not research_fn:
        return None

    try:
        await init_professional_crypto_ai_embedded()
        verdict = await research_fn(symbol, include_external=PRO_AI_AUTOSIGNAL_INCLUDE_EXTERNAL)
        action = str(verdict.get("action", "NO_SIGNAL")).upper()
        direction = _ai_verdict_action_to_direction(action)
        scan_mem[symbol] = {
            "last_ts": now_ts,
            "action": action,
            "direction": verdict.get("direction"),
            "confidence": verdict.get("confidence"),
            "signal_score": verdict.get("signal_score"),
            "risk": verdict.get("risk"),
            "send_signal": bool(verdict.get("send_signal")),
        }
        if not verdict.get("send_signal"):
            return None
        if direction and ai_auto_recently_locked(symbol, direction):
            stats["cooldown_reject"] = stats.get("cooldown_reject", 0) + 1
            return None
        payload = build_ai_auto_signal_payload(symbol, verdict)
        if payload:
            stats["professional_ai_auto_signal"] = stats.get("professional_ai_auto_signal", 0) + 1
        return payload
    except Exception as e:
        stats["professional_ai_error"] = stats.get("professional_ai_error", 0) + 1
        logger.warning("AI otomatik sinyal tarama hatası %s: %s", symbol, str(e)[:180])
        return None


async def ai_auto_signal_loop() -> None:
    global ai_pointer
    if not PRO_AI_AUTOSIGNAL_LOOP_ENABLED:
        return
    while True:
        try:
            if professional_ai_enabled() and COINS:
                sent_this_cycle = 0
                batch_size = max(1, min(PRO_AI_AUTOSIGNAL_BATCH_SIZE, len(COINS)))
                batch: List[str] = []
                for _ in range(batch_size):
                    batch.append(COINS[ai_pointer % len(COINS)])
                    ai_pointer += 1
                for sym in batch:
                    payload = await maybe_build_ai_auto_signal_for_symbol(sym)
                    if payload:
                        await maybe_send_signal(payload)
                        sent_this_cycle += 1
                        if sent_this_cycle >= max(1, PRO_AI_AUTOSIGNAL_MAX_SEND_PER_CYCLE):
                            break
        except Exception as e:
            logger.exception("ai_auto_signal_loop hata: %s", e)
        await asyncio.sleep(max(5.0, PRO_AI_AUTOSIGNAL_INTERVAL_SEC))





# =========================================================
# V6.1 PRO FINAL KAPILAR: SR / REJİM / MAKRO / HATA HAFIZASI
# =========================================================
def _cluster_levels(values: List[float], tolerance_pct: float = SR_CLUSTER_TOLERANCE_PCT) -> List[Dict[str, Any]]:
    vals = sorted([v for v in values if v > 0])
    clusters: List[List[float]] = []
    for v in vals:
        if not clusters:
            clusters.append([v]); continue
        ref = avg(clusters[-1])
        if abs(pct_change(ref, v)) <= tolerance_pct:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    out = []
    for c in clusters:
        if len(c) >= SR_MIN_TOUCHES:
            out.append({"level": avg(c), "touches": len(c)})
    return sorted(out, key=lambda x: x["level"])


def build_support_resistance_context(k1: List[List[Any]], k5: List[List[Any]], entry: float, tp1: float, direction: str) -> Dict[str, Any]:
    hs = highs(k1[-90:]) + highs(k5[-60:])
    ls = lows(k1[-90:]) + lows(k5[-60:])
    supports = _cluster_levels(ls)
    resistances = _cluster_levels(hs)
    nearest_support_below = max([x for x in supports if x["level"] < entry], key=lambda x: x["level"], default={})
    nearest_resistance_above = min([x for x in resistances if x["level"] > entry], key=lambda x: x["level"], default={})
    direction = (direction or "SHORT").upper()
    block = False; reason = "SR temiz"
    if direction == "SHORT":
        # Entry ile TP1 arasında kuvvetli destek varsa TP1 önünde duvar vardır.
        walls = [x for x in supports if tp1 < x["level"] < entry]
        wall = max(walls, key=lambda x: x["touches"], default={})
        if wall and abs(pct_change(entry, wall["level"])) <= abs(pct_change(entry, tp1)) + SR_TP1_WALL_BUFFER_PCT:
            block = True
            reason = f"TP1 önünde destek duvarı {fmt_num(wall['level'])} | touches={wall['touches']}"
    else:
        walls = [x for x in resistances if entry < x["level"] < tp1]
        wall = max(walls, key=lambda x: x["touches"], default={})
        if wall and abs(pct_change(entry, wall["level"])) <= abs(pct_change(entry, tp1)) + SR_TP1_WALL_BUFFER_PCT:
            block = True
            reason = f"TP1 önünde direnç duvarı {fmt_num(wall['level'])} | touches={wall['touches']}"
    return {
        "enabled": True, "block": block, "reason": reason,
        "support": nearest_support_below.get("level", 0), "support_touches": nearest_support_below.get("touches", 0),
        "resistance": nearest_resistance_above.get("level", 0), "resistance_touches": nearest_resistance_above.get("touches", 0),
    }


def detect_regime_context(k1: List[List[Any]], k5: List[List[Any]]) -> Dict[str, Any]:
    if len(k1) < 50 or len(k5) < 50:
        return {"regime": "UNKNOWN", "score": 0, "reason": "veri yetersiz"}
    c1 = closes(k1); c5 = closes(k5)
    e9 = ema(c1, 9); e21 = ema(c1, 21); e50 = ema(c5, 50)
    r1 = rsi(c1, 14); r5 = rsi(c5, 14)
    move20 = pct_change(c1[-21], c1[-1]) if len(c1) >= 22 else 0.0
    score = 0.0
    reasons = []
    if c1[-1] > e9[-1] > e21[-1]: score += 2; reasons.append("1m EMA yukarı")
    if c1[-1] < e9[-1] < e21[-1]: score -= 2; reasons.append("1m EMA aşağı")
    if c5[-1] > e50[-1]: score += 1; reasons.append("5m EMA50 üstü")
    if c5[-1] < e50[-1]: score -= 1; reasons.append("5m EMA50 altı")
    if r1[-1] > 60 and r5[-1] > 56: score += 1; reasons.append("RSI yukarı rejim")
    if r1[-1] < 40 and r5[-1] < 44: score -= 1; reasons.append("RSI aşağı rejim")
    if move20 > 0.9: score += 1; reasons.append(f"20m güçlü yukarı %{move20:.2f}")
    if move20 < -0.9: score -= 1; reasons.append(f"20m güçlü aşağı %{move20:.2f}")
    if score >= 3:
        reg = "UPTREND"
    elif score <= -3:
        reg = "DOWNTREND"
    else:
        reg = "RANGE"
    return {"regime": reg, "score": round(score, 2), "reason": " | ".join(reasons[:6])}


async def build_macro_context() -> Dict[str, Any]:
    out = {"enabled": MACRO_FILTER_ENABLED, "btc_15m": 0.0, "btc_1h": 0.0, "eth_15m": 0.0, "bias": "NÖTR", "reason": "-"}
    if not MACRO_FILTER_ENABLED:
        return out
    try:
        btc1 = await get_klines("BTC-USDT-SWAP", "1m", 70)
        eth1 = await get_klines("ETH-USDT-SWAP", "1m", 70)
        if len(btc1) >= 61:
            cb = closes(btc1); out["btc_15m"] = round(pct_change(cb[-16], cb[-1]), 2); out["btc_1h"] = round(pct_change(cb[-61], cb[-1]), 2)
        if len(eth1) >= 16:
            ce = closes(eth1); out["eth_15m"] = round(pct_change(ce[-16], ce[-1]), 2)
        if out["btc_15m"] >= MACRO_BTC_STRONG_MOVE_PCT or out["eth_15m"] >= MACRO_ETH_STRONG_MOVE_PCT:
            out["bias"] = "RISK_ON_UP"
        elif out["btc_15m"] <= -MACRO_BTC_STRONG_MOVE_PCT or out["eth_15m"] <= -MACRO_ETH_STRONG_MOVE_PCT:
            out["bias"] = "RISK_OFF_DOWN"
        out["reason"] = f"BTC15={out['btc_15m']} BTC1h={out['btc_1h']} ETH15={out['eth_15m']} bias={out['bias']}"
    except Exception as e:
        out["reason"] = f"Makro okunamadı: {str(e)[:80]}"
    return out


def mistake_signature_from_payload(res: Dict[str, Any]) -> str:
    direction = str(res.get("direction", "SHORT")).upper()
    sym = normalize_symbol(str(res.get("symbol", "")))
    base = coin_base_from_symbol(sym)
    rsi1 = safe_float(res.get("rsi1", 50)); rsi5 = safe_float(res.get("rsi5", 50)); rsi15 = safe_float(res.get("rsi15", 50))
    br = safe_float(res.get("breakdown_score", 0)); q = safe_float(res.get("quality_score", 0))
    whale = res.get("whale_eye", {}) if isinstance(res.get("whale_eye"), dict) else {}
    wh_conf = str(whale.get("whale_confidence", res.get("whale_confidence", "-")))
    binance = str(res.get("binance_confirm_status", "-"))
    def bucket(v, cuts):
        for name, lim in cuts:
            if v <= lim: return name
        return "HIGH"
    parts = [
        direction,
        bucket(rsi1, [("RSI1_LOW", 42), ("RSI1_MID", 58), ("RSI1_HOT", 70)]),
        bucket(rsi5, [("RSI5_LOW", 45), ("RSI5_MID", 60), ("RSI5_HOT", 72)]),
        bucket(rsi15, [("RSI15_LOW", 45), ("RSI15_MID", 60), ("RSI15_HOT", 72)]),
        bucket(br, [("BR_WEAK", 5), ("BR_OK", 8), ("BR_STRONG", 12)]),
        bucket(q, [("Q_WEAK", 5), ("Q_MID", 7), ("Q_GOOD", 9)]),
        f"WHALE_{wh_conf}", f"BIN_{binance}",
    ]
    # Coin bazlı değil pattern bazlı öğrensin; fakat base de not olarak kaydedilir.
    return "|".join(parts)


def mistake_memory_should_block(res: Dict[str, Any]) -> Tuple[bool, str]:
    if not MISTAKE_MEMORY_ENABLED:
        return False, "Hata hafızası kapalı"
    mm = memory.setdefault("mistake_memory", {})
    patterns = mm.setdefault("patterns", {})
    sig = mistake_signature_from_payload(res)
    rec = patterns.get(sig, {})
    stops = int(safe_float(rec.get("stops", 0), 0))
    last_ts = safe_float(rec.get("last_ts", 0), 0)
    if stops >= MISTAKE_MEMORY_MIN_STOPS and time.time() - last_ts <= MISTAKE_MEMORY_BLOCK_HOURS * 3600:
        return True, f"HATA HAFIZASI BLOK: bu pattern son {MISTAKE_MEMORY_BLOCK_HOURS:.0f}s içinde stop oldu | {sig}"
    return False, "Hata hafızası temiz"


def learn_from_stopped_signal(sym: str, direction: str, rec: Dict[str, Any], result: Dict[str, Any]) -> None:
    if not MISTAKE_MEMORY_ENABLED:
        return
    payload = copy.deepcopy(rec.get("signal_snapshot", {}))
    if not payload:
        payload = {"symbol": sym, "direction": direction, **rec}
    sig = mistake_signature_from_payload(payload)
    mm = memory.setdefault("mistake_memory", {})
    patterns = mm.setdefault("patterns", {})
    cur = patterns.setdefault(sig, {"stops": 0, "examples": []})
    cur["stops"] = int(safe_float(cur.get("stops", 0), 0)) + 1
    cur["last_ts"] = time.time()
    cur["last_symbol"] = sym
    cur["last_direction"] = direction
    cur["last_reason"] = str(result.get("note", "STOP"))[:240]
    examples = cur.setdefault("examples", [])
    examples.append({"ts": time.time(), "symbol": sym, "direction": direction, "entry": rec.get("entry"), "stop": rec.get("stop"), "outcome": "STOP"})
    cur["examples"] = examples[-8:]
    stats["mistake_memory_learn"] = stats.get("mistake_memory_learn", 0) + 1


def position_management_summary(klines: List[List[Any]], direction: str, entry: float, stop: float, tp1: float, tp2: float, tp3: float) -> str:
    if not POSITION_MANAGEMENT_ENABLED or not klines or entry <= 0:
        return "Pozisyon yönetimi kapalı/veri yok."
    direction = (direction or "SHORT").upper()
    hs = highs(klines); ls = lows(klines)
    if direction == "LONG":
        best = max(hs); worst = min(ls)
        mfe = pct_change(entry, best); mae = pct_change(entry, worst)
        trail = max(stop, entry * (1 + TRAILING_LOCK_PCT_AFTER_TP1 / 100.0)) if best >= tp1 and TRAILING_AFTER_TP1_ENABLED else stop
        return f"MFE %{mfe:.2f} | MAE %{mae:.2f} | TP1 sonrası öneri trailing stop: {fmt_num(trail)}"
    best = min(ls); worst = max(hs)
    mfe = pct_change(entry, best) * -1; mae = pct_change(entry, worst) * -1
    trail = min(stop, entry * (1 - TRAILING_LOCK_PCT_AFTER_TP1 / 100.0)) if best <= tp1 and TRAILING_AFTER_TP1_ENABLED else stop
    return f"MFE %{mfe:.2f} | MAE %{mae:.2f} | TP1 sonrası öneri trailing stop: {fmt_num(trail)}"


async def apply_professional_final_gates(res: Dict[str, Any]) -> Dict[str, Any]:
    if not PRO_FINAL_GATES_ENABLED or res.get("stage") != "SIGNAL":
        return res
    p = copy.deepcopy(res)
    sym = normalize_symbol(str(p.get("symbol", "")))
    direction = str(p.get("direction", "SHORT")).upper()
    whale = p.get("whale_eye", {}) if isinstance(p.get("whale_eye"), dict) else {}
    whale_score = safe_float(whale.get("total_score", p.get("whale_score", 0)))
    weak_whale = whale_score < PRO_GATE_WHALE_OVERRIDE_SCORE

    # Hata hafızası
    block, reason = mistake_memory_should_block(p)
    if block:
        p["stage"] = "READY"; p["signal_label"] = "İÇ TAKİP"; p["reason"] = f"{p.get('reason','')} | {reason}"
        stats["mistake_memory_block"] = stats.get("mistake_memory_block", 0) + 1
        return p

    try:
        k1 = await get_klines(sym, "1m", 140)
        k5 = await get_klines(sym, "5m", 120)
    except Exception:
        k1, k5 = [], []
    if len(k1) >= 50 and len(k5) >= 40:
        sr = build_support_resistance_context(k1, k5, safe_float(p.get("price", 0)), safe_float(p.get("tp1", 0)), direction)
        p["sr"] = sr
        if SR_FILTER_ENABLED and SR_HARD_BLOCK_ENABLED and sr.get("block") and (not PRO_GATE_BLOCK_ONLY_WEAK_WHALE or weak_whale):
            p["stage"] = "READY"; p["signal_label"] = "İÇ TAKİP"; p["reason"] = f"{p.get('reason','')} | SR BLOK: {sr.get('reason')}"
            stats["sr_block"] = stats.get("sr_block", 0) + 1
            return p
        regime = detect_regime_context(k1, k5)
        p["regime"] = regime
        if REGIME_FILTER_ENABLED and weak_whale:
            if direction == "SHORT" and regime.get("regime") == "UPTREND" and safe_float(p.get("breakdown_score", 0)) < BREAKDOWN_ASSIST_STRONG_SCORE:
                p["stage"] = "READY"; p["signal_label"] = "İÇ TAKİP"; p["reason"] = f"{p.get('reason','')} | REJİM BLOK: güçlü yukarı rejimde zayıf short | {regime.get('reason')}"
                stats["regime_block"] = stats.get("regime_block", 0) + 1
                return p
            if direction == "LONG" and regime.get("regime") == "DOWNTREND" and safe_float(p.get("long_structure_score", p.get("breakdown_score", 0))) < ICT_MIN_CHOCH_SCORE:
                p["stage"] = "READY"; p["signal_label"] = "İÇ TAKİP"; p["reason"] = f"{p.get('reason','')} | REJİM BLOK: aşağı rejimde zayıf long | {regime.get('reason')}"
                stats["regime_block"] = stats.get("regime_block", 0) + 1
                return p

    macro = await build_macro_context()
    p["macro"] = macro
    if MACRO_FILTER_ENABLED and weak_whale:
        if direction == "SHORT" and macro.get("bias") == "RISK_ON_UP" and safe_float(p.get("breakdown_score", 0)) < BREAKDOWN_ASSIST_STRONG_SCORE:
            p["stage"] = "READY"; p["signal_label"] = "İÇ TAKİP"; p["reason"] = f"{p.get('reason','')} | MAKRO BLOK: BTC/ETH yukarı akarken zayıf short | {macro.get('reason')}"
            stats["macro_block"] = stats.get("macro_block", 0) + 1
            return p
        if direction == "LONG" and macro.get("bias") == "RISK_OFF_DOWN":
            p["stage"] = "READY"; p["signal_label"] = "İÇ TAKİP"; p["reason"] = f"{p.get('reason','')} | MAKRO BLOK: BTC/ETH aşağı akarken zayıf long | {macro.get('reason')}"
            stats["macro_block"] = stats.get("macro_block", 0) + 1
            return p
    return p


async def short_15m_ma_gate_reason(symbol: str, res: Dict[str, Any]) -> str:
    """
    15m sarı MA7, pembe MA25 altına inmeden SHORT dış sinyali basılmaz.
    Bu kapı normal SHORT ve AI otomatik köprüden gelen SHORT sinyallerini de kontrol eder.
    """
    if not SHORT_15M_MA_GATE_ENABLED:
        return ""
    if str(res.get("direction", "SHORT")).upper() != "SHORT":
        return ""

    ma_fast = safe_float(res.get("ma_fast_15m", 0), 0)
    ma_slow = safe_float(res.get("ma_slow_15m", 0), 0)

    # Payload içinde yoksa canlı 15m mumdan oku. Böylece AI otomatik payload da bypass edemez.
    if ma_fast <= 0 or ma_slow <= 0:
        try:
            k15 = await get_klines(symbol, "15m", max(60, SHORT_15M_SLOW_MA + 10))
            if len(k15) < SHORT_15M_SLOW_MA + 3:
                return "15m MA kapısı: veri yetersiz, dış SHORT yok."
            c15 = closes(k15)
            e_fast = ema(c15, SHORT_15M_FAST_MA)
            e_slow = ema(c15, SHORT_15M_SLOW_MA)
            ma_fast = safe_float(e_fast[-1], 0)
            ma_slow = safe_float(e_slow[-1], 0)
            res["ma_fast_15m"] = round(ma_fast, 8)
            res["ma_slow_15m"] = round(ma_slow, 8)
        except Exception as e:
            return f"15m MA kapısı okunamadı: {str(e)[:80]}"

    if ma_fast >= ma_slow:
        return (
            f"15m MA kapısı BLOK: sarı MA{SHORT_15M_FAST_MA} "
            f"({fmt_num(ma_fast)}) pembe MA{SHORT_15M_SLOW_MA} "
            f"({fmt_num(ma_slow)}) altına inmedi; SHORT sadece iç takip."
        )
    return ""


def short_context_guard_reason(res: Dict[str, Any], binance_status: str = "") -> str:
    """
    ONE-USDT tarzı stop hatası koruması.
    SHORT dış sinyali şu ters kombinasyonlarda sessiz takibe düşürür:
      - CVD BULLISH_DIVERGENCE + Binance FAIL
      - CVD BULLISH_DIVERGENCE + zayıf pump + düşük RSI1
      - Binance FAIL + zayıf pump + düşük RSI1
    Amaç ZRX tarzı BEARISH_CVD + Binance PASS + şişkin RSI sinyallerini öldürmemek.
    """
    if not SHORT_CONTEXT_GUARD_ENABLED:
        return ""
    if str(res.get("direction", "SHORT")).upper() != "SHORT":
        return ""

    whale = res.get("whale_eye") if isinstance(res.get("whale_eye"), dict) else {}
    cvd = whale.get("cvd") if isinstance(whale.get("cvd"), dict) else {}
    cvd_div = str(cvd.get("divergence", "")).upper()

    status = str(binance_status or res.get("binance_confirm_status", "")).upper()
    pump20 = safe_float(res.get("pump_20m", 0), 0)
    pump1h = safe_float(res.get("pump_1h", 0), 0)
    rsi1 = safe_float(res.get("rsi1", 50), 50)

    cvd_bullish = cvd_div == "BULLISH_DIVERGENCE"
    binance_fail = status in ("FAIL", "HARD_FAIL")
    weak_pump = pump20 < SHORT_CONTEXT_WEAK_PUMP_20M and pump1h < SHORT_CONTEXT_WEAK_PUMP_1H
    low_rsi = rsi1 <= SHORT_CONTEXT_LATE_RSI1

    if SHORT_BLOCK_ON_BULLISH_CVD_AND_BINANCE_FAIL and cvd_bullish and binance_fail:
        return (
            "ONE STOP KORUMA: SHORT için ters CVD var "
            f"({cvd_div}) ve Binance teyit {status}; dış sinyal yok."
        )

    if SHORT_CONTEXT_BLOCK_BULLISH_CVD_WEAK_PUMP_LOW_RSI and cvd_bullish and weak_pump and low_rsi:
        return (
            "ONE STOP KORUMA: CVD bullish + pump zayıf "
            f"(20m={pump20:.2f}, 1s={pump1h:.2f}) + RSI1 düşük {rsi1:.1f}; geç/ters SHORT dışarı basılmaz."
        )

    if SHORT_CONTEXT_BLOCK_BINANCE_FAIL_WEAK_PUMP_LOW_RSI and binance_fail and weak_pump and low_rsi:
        return (
            "ONE STOP KORUMA: Binance FAIL + pump zayıf "
            f"(20m={pump20:.2f}, 1s={pump1h:.2f}) + RSI1 düşük {rsi1:.1f}; sadece iç takip."
        )

    return ""


async def maybe_send_signal(res: Dict[str, Any]) -> None:
    symbol = res["symbol"]
    stage = res["stage"]
    direction = str(res.get("direction", "SHORT")).upper()
    expected_label = "LONG AL" if direction == "LONG" else "SHORT AL"

    if stage == "SIGNAL":
        if direction == "LONG":
            res = enforce_single_long_al_rules(res)
        else:
            res = enforce_single_short_al_rules(res)

        # Profesyonel Kripto AI: gerçek sinyal gönderilmeden hemen önce derin araştırma yapar.
        # Uygun değilse dışarıya BEKLE/RED/AI_YOK gibi etiket basmadan sinyali sessizce susturur.
        if professional_ai_enabled() and not res.get("professional_ai_checked"):
            try:
                res = await run_professional_ai_on_payload_embedded(res)
                if res.get("send_signal") is False:
                    stats["professional_ai_silent"] = stats.get("professional_ai_silent", 0) + 1
                    logger.info("Profesyonel AI sinyali sessizce susturdu %s %s: %s", direction, symbol, res.get("_internal_ai_silent_reason", "-"))
                    update_hot_memory({**copy.deepcopy(res), "stage": "READY"})
                    return
            except Exception as e:
                stats["professional_ai_error"] = stats.get("professional_ai_error", 0) + 1
                logger.warning("Profesyonel AI sinyal kontrol hatası %s %s: %s", direction, symbol, str(e)[:180])
                if not professional_ai_fail_open():
                    update_hot_memory({**copy.deepcopy(res), "stage": "READY"})
                    return

        if res.get("ai_auto_promoted"):
            gate_ok, gate_reason = validate_ai_auto_final_gate(res)
            if not gate_ok:
                stats["ai_auto_final_block"] = stats.get("ai_auto_final_block", 0) + 1
                if direction == "SHORT" and "GEÇ SHORT" in gate_reason:
                    stats["ai_auto_late_short_block"] = stats.get("ai_auto_late_short_block", 0) + 1
                if direction == "LONG" and "GEÇ LONG" in gate_reason:
                    stats["ai_auto_late_long_block"] = stats.get("ai_auto_late_long_block", 0) + 1
                logger.info("AI otomatik final kapı son kontrol blok %s %s: %s", direction, symbol, gate_reason)
                update_hot_memory({**copy.deepcopy(res), "stage": "READY", "reason": f"{res.get('reason', '')} | {gate_reason}"})
                return
            res["reason"] = f"{res.get('reason', '')} | {gate_reason}"[:1400]

        if res.get("stage") != "SIGNAL" or str(res.get("signal_label", "")) != expected_label:
            logger.info("%s sinyali susturdu %s: %s", expected_label, symbol, res.get("reason", "-"))
            update_hot_memory(copy.deepcopy(res))
            return

        # Son güvenlik: AI otomatik dahil hiçbir SHORT, 15m MA7 < MA25 olmadan dışarı çıkamaz.
        if direction == "SHORT":
            ma_gate = await short_15m_ma_gate_reason(symbol, res)
            if ma_gate:
                stats["short_15m_ma_gate_block"] = stats.get("short_15m_ma_gate_block", 0) + 1
                logger.info("15M MA SHORT BLOK %s: %s", symbol, ma_gate)
                update_hot_memory({**copy.deepcopy(res), "stage": "READY", "reason": f"{res.get('reason', '')} | {ma_gate}"[:1400]})
                return

        logger.info("%s ÜRETİLDİ %s skor=%s", expected_label, symbol, res.get("score"))

        now_attempt = time.time()
        spacing_guard = SIGNAL_SPACING_SEC if SIGNAL_SPACING_SEC > 0 else INTERNAL_SIGNAL_SPACING_SEC
        last_attempt = safe_float(memory.get("last_signal_attempt_ts", 0))
        if spacing_guard > 0 and now_attempt - last_attempt < spacing_guard:
            stats["scan_signal_suppressed"] += 1
            logger.info("İÇ SİNYAL ARALIĞI KORUMASI %s %s", direction, symbol)
            update_hot_memory({**copy.deepcopy(res), "stage": "READY"})
            return
        memory["last_signal_attempt_ts"] = now_attempt

        # V6.1 PRO: SR / rejim / makro / hata hafızası son kapı
        res = await apply_professional_final_gates(res)
        if res.get("stage") != "SIGNAL":
            logger.info("V6.1 PRO final kapı sinyali takipte tuttu %s %s: %s", direction, symbol, res.get("reason", "-"))
            update_hot_memory(copy.deepcopy(res))
            return

        if daily_trade_already_sent(symbol, direction):
            stats["daily_short_block"] += 1
            logger.info("GÜNLÜK %s KİLİDİ %s", direction, symbol)
            update_hot_memory({**copy.deepcopy(res), "stage": "READY"})
            return

        if get_today_trade_sent_count(direction) >= get_daily_trade_limit(direction):
            stats["daily_total_block"] += 1
            logger.info("GÜNLÜK TOPLAM %s LİMİTİ DOLDU %s", direction, symbol)
            update_hot_memory({**copy.deepcopy(res), "stage": "READY"})
            return

        # AI otomatik köprüden gelen sinyallerde tekrar/spam kilidi gönderimden ÖNCE atılır.
        # Sebep: Telegram mesajı gitmiş ama API cevabı/timeout yüzünden ok=False dönebilir;
        # bu durumda hafıza yazılmazsa aynı coin 2-3 dk içinde tekrar basar.
        if res.get("ai_auto_promoted"):
            if ai_auto_recently_locked(symbol, direction):
                stats["cooldown_reject"] = stats.get("cooldown_reject", 0) + 1
                logger.info("AI OTOMATİK TEKRAR KİLİDİ %s %s", direction, symbol)
                update_hot_memory({**copy.deepcopy(res), "stage": "READY"})
                return
            if PRO_AI_AUTOSIGNAL_PRELOCK_ENABLED:
                mark_ai_auto_signal_lock(symbol, direction, res)
                set_daily_trade_sent(symbol, res)
                save_memory()

        if direction == "SHORT":
            confirm = await confirm_signal_on_binance(res)
            res["data_engine"] = "OKX SWAP"
            res["binance_confirm_status"] = confirm.get("status", "YOK")
            res["binance_confirm_score"] = confirm.get("score", 0)
            res["binance_symbol"] = confirm.get("binance_symbol", normalize_binance_symbol(symbol))
            res["binance_price"] = confirm.get("binance_price", 0)
            res["binance_price_gap_pct"] = confirm.get("price_gap_pct", 0)
            res["binance_confirm_reason"] = confirm.get("reason", "-")

            confirm_status = str(confirm.get("status", "YOK"))
            if confirm_status == "PASS":
                stats["binance_confirm_pass"] += 1
            elif confirm_status == "SOFT_PASS":
                stats["binance_confirm_soft"] += 1
            elif confirm_status in ("FAIL", "HARD_FAIL"):
                stats["binance_confirm_fail"] += 1
                if confirm_status == "HARD_FAIL":
                    stats["signal_downgraded_by_binance"] += 1
                    logger.info("BINANCE TEYİDİ RED %s", symbol)
                    downgraded = copy.deepcopy(res)
                    downgraded["stage"] = "READY"
                    update_hot_memory(downgraded)
                    return
            elif confirm_status == "UNAVAILABLE":
                stats["binance_confirm_unavailable"] += 1

            # ONE-USDT stop hatası güvenlik kapısı:
            # Ters CVD + Binance FAIL + zayıf pump/düşük RSI SHORT sinyalini dışarı göndermeden iç takibe alır.
            context_guard = short_context_guard_reason(res, confirm_status)
            if context_guard:
                stats["short_context_guard_block"] = stats.get("short_context_guard_block", 0) + 1
                logger.info("SHORT CONTEXT GUARD BLOK %s: %s", symbol, context_guard)
                guarded = copy.deepcopy(res)
                guarded["stage"] = "READY"
                guarded["signal_label"] = "İÇ TAKİP"
                guarded["reason"] = f"{guarded.get('reason', '')} | {context_guard}"[:1400]
                update_hot_memory(guarded)
                return
        else:
            res["data_engine"] = "OKX SWAP + ICT LONG"
            res["binance_confirm_status"] = "NOT_USED"
            res["binance_symbol"] = normalize_binance_symbol(symbol)
            res["binance_price"] = 0
            res["binance_price_gap_pct"] = 0
            res["binance_confirm_reason"] = "LONG motoru ayrı teyitle çalışır"

        ok = await safe_send_telegram(build_signal_message(res))
        if ok:
            logger.info("TELEGRAM GÖNDERİLDİ %s %s", expected_label, symbol)
            stats["signal_sent"] += 1
            memory["last_signal_ts"] = time.time()
            if direction == "LONG":
                stats["long_signal_sent"] += 1
            set_daily_trade_sent(symbol, res)
            if res.get("ai_auto_promoted"):
                mark_ai_auto_signal_lock(symbol, direction, res)
            follow_key = f"{direction}:{symbol}"
            memory.setdefault("follows", {})[follow_key] = {
                "created_ts": time.time(), "symbol": symbol, "direction": direction,
                "entry": res["price"], "stop": res["stop"],
                "tp1": res["tp1"], "tp2": res["tp2"], "tp3": res["tp3"],
                "stage": "SIGNAL", "done": False, "sent_ts": time.time(),
                "signal_snapshot": {
                    "symbol": symbol, "direction": direction, "score": res.get("score"),
                    "quality_score": res.get("quality_score"), "breakdown_score": res.get("breakdown_score"),
                    "rsi1": res.get("rsi1"), "rsi5": res.get("rsi5"), "rsi15": res.get("rsi15"),
                    "pump_10m": res.get("pump_10m"), "pump_20m": res.get("pump_20m"), "pump_1h": res.get("pump_1h"),
                    "whale_eye": res.get("whale_eye", {}), "binance_confirm_status": res.get("binance_confirm_status", "-"),
                    "sr": res.get("sr", {}), "regime": res.get("regime", {}), "macro": res.get("macro", {}),
                    "reason": res.get("reason", ""),
                }
            }
            memory.get("hot", {}).pop(symbol, None)
            memory.get("trend_watch", {}).pop(symbol, None)
        else:
            logger.warning("TELEGRAM GÖNDERİLEMEDİ %s %s", expected_label, symbol)
        return

    if stage in ("READY", "HOT"):
        update_hot_memory(res)
        return


def select_best_signals(signals: List[Dict[str, Any]], limit: int = MAX_SIGNAL_PER_SCAN) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if not signals:
        return [], []
    ordered = sorted(signals, key=lambda r: safe_float(r.get("score", 0)) + safe_float(r.get("whale_eye", {}).get("total_score", 0)), reverse=True)
    keep = ordered[:max(1, limit)]
    suppressed = ordered[max(1, limit):]
    return keep, suppressed


def get_hot_symbols(limit: int = MAX_HOT_CANDIDATES) -> List[str]:
    hot = memory.get("hot", {})
    trend_watch = memory.get("trend_watch", {})
    merged: Dict[str, Dict[str, Any]] = {}
    for sym, rec in hot.items():
        merged[sym] = rec
    for sym, rec in trend_watch.items():
        cur = merged.get(sym, {})
        if safe_float(rec.get("score", 0)) > safe_float(cur.get("score", 0)):
            merged[sym] = rec
    items = sorted(merged.items(), key=lambda x: safe_float(x[1].get("score", 0)), reverse=True)
    return [k for k, _ in items if not is_blocked_coin_symbol(k)][:limit]


def pick_general_symbols(batch_size: int = MAX_DEEP_ANALYSIS_PER_CYCLE) -> List[str]:
    global deep_pointer
    if not COINS:
        return []
    out = []
    n = len(COINS)
    for _ in range(min(batch_size, n)):
        out.append(COINS[deep_pointer % n])
        deep_pointer += 1
    return out


async def analyze_separate_engines(symbol: str, tickers24: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    short_res = await analyze_symbol(symbol, tickers24)
    long_res = await analyze_long_symbol(symbol, tickers24) if LONG_ENGINE_ENABLED else None
    for res in (short_res, long_res):
        if res:
            results.append(res)
    signal_dirs = {str(r.get("direction", "SHORT")).upper() for r in results if r.get("stage") == "SIGNAL"}
    if "SHORT" in signal_dirs and "LONG" in signal_dirs:
        stats["long_conflict_block"] += 1
        out: List[Dict[str, Any]] = []
        for r in results:
            r = copy.deepcopy(r)
            r["stage"] = "READY"
            r["signal_label"] = "İÇ TAKİP"
            r["reason"] = f"{r.get('reason', '')} | LONG/SHORT çakıştı"
            out.append(r)
        return out
    return results


async def hot_scan_loop() -> None:
    while True:
        try:
            cleanup_memory()
            tickers24 = await get_24h_tickers()
            hot_syms = get_hot_symbols(MAX_HOT_CANDIDATES)
            if not hot_syms:
                await asyncio.sleep(HOT_SCAN_INTERVAL_SEC)
                continue

            signal_candidates: List[Dict[str, Any]] = []
            for sym in hot_syms:
                engine_results = await analyze_separate_engines(sym, tickers24)
                if not engine_results:
                    continue
                stats["analyzed"] += 1
                for res in engine_results:
                    if res["stage"] == "SIGNAL":
                        signal_candidates.append(res)
                    elif res["stage"] in ("READY", "HOT"):
                        update_hot_memory(res)

            chosen, suppressed = select_best_signals(signal_candidates)
            for res in suppressed:
                stats["scan_signal_suppressed"] += 1
            for res in chosen:
                await maybe_send_signal(res)
        except Exception as e:
            logger.exception("hot_scan_loop hata: %s", e)
        await asyncio.sleep(HOT_SCAN_INTERVAL_SEC)


async def deep_scan_loop() -> None:
    while True:
        try:
            cleanup_memory()
            tickers24 = await get_24h_tickers()
            batch = pick_general_symbols(MAX_DEEP_ANALYSIS_PER_CYCLE)
            signal_candidates: List[Dict[str, Any]] = []
            for sym in batch:
                engine_results = await analyze_separate_engines(sym, tickers24)
                if not engine_results:
                    continue
                stats["analyzed"] += 1
                for res in engine_results:
                    if res["stage"] == "SIGNAL":
                        signal_candidates.append(res)
                    elif res["stage"] in ("HOT", "READY"):
                        update_hot_memory(res)

            chosen, suppressed = select_best_signals(signal_candidates)
            for res in suppressed:
                stats["scan_signal_suppressed"] += 1
            for res in chosen:
                await maybe_send_signal(res)
        except Exception as e:
            logger.exception("deep_scan_loop hata: %s", e)
        await asyncio.sleep(DEEP_SCAN_INTERVAL_SEC)


async def heartbeat_loop() -> None:
    if not AUTO_HEARTBEAT:
        return
    while True:
        try:
            await safe_send_telegram(build_heartbeat_message())
        except Exception as e:
            logger.exception("heartbeat_loop hata: %s", e)
        await asyncio.sleep(max(60, HEARTBEAT_INTERVAL_SEC))



def evaluate_tp_stop_path(
    klines: List[List[Any]],
    direction: str,
    sent_ts: float,
    entry: float,
    stop: float,
    tp1: float,
    tp2: float,
    tp3: float,
) -> Dict[str, Any]:
    """
    Sinyalden sonraki 1m mumları sırayla tarar.
    Son fiyata göre karar vermez; önce stop mu TP mi geldi onu bulur.
    Aynı mumda hem stop hem TP görünüyorsa güvenli tarafta kalıp STOP sayar.
    """
    direction = (direction or "SHORT").upper()
    sent_ms = int(sent_ts * 1000)
    checked = 0
    best_tp = "YOK"
    best_tp_price = 0.0

    for k in klines:
        start_ms = kline_start_ms(k)
        close_ms = start_ms + interval_to_milliseconds("1m") if start_ms else 0
        if close_ms and close_ms <= sent_ms:
            continue
        checked += 1
        high = safe_float(k[2])
        low = safe_float(k[3])
        close = safe_float(k[4])
        ts_text = tr_str(start_ms / 1000.0) if start_ms else "-"

        if direction == "LONG":
            stop_hit = stop > 0 and low <= stop
            tp1_hit = tp1 > 0 and high >= tp1
            tp2_hit = tp2 > 0 and high >= tp2
            tp3_hit = tp3 > 0 and high >= tp3
            if stop_hit and (tp1_hit or tp2_hit or tp3_hit):
                return {"outcome": "STOP", "hit": "STOP", "hit_price": stop, "hit_time": ts_text, "checked": checked, "note": "Aynı mumda TP ve stop görüldü; güvenli hesapla stop önce kabul edildi."}
            if stop_hit:
                return {"outcome": "STOP", "hit": "STOP", "hit_price": stop, "hit_time": ts_text, "checked": checked, "note": "Stop mum taramasında önce geldi."}
            if tp3_hit:
                return {"outcome": "TP3", "hit": "TP3", "hit_price": tp3, "hit_time": ts_text, "checked": checked, "note": "TP3 mum taramasında stop öncesi geldi."}
            if tp2_hit:
                best_tp, best_tp_price = "TP2", tp2
                return {"outcome": "TP2", "hit": "TP2", "hit_price": tp2, "hit_time": ts_text, "checked": checked, "note": "TP2 mum taramasında stop öncesi geldi."}
            if tp1_hit:
                best_tp, best_tp_price = "TP1", tp1
                return {"outcome": "TP1", "hit": "TP1", "hit_price": tp1, "hit_time": ts_text, "checked": checked, "note": "TP1 mum taramasında stop öncesi geldi."}
        else:
            stop_hit = stop > 0 and high >= stop
            tp1_hit = tp1 > 0 and low <= tp1
            tp2_hit = tp2 > 0 and low <= tp2
            tp3_hit = tp3 > 0 and low <= tp3
            if stop_hit and (tp1_hit or tp2_hit or tp3_hit):
                return {"outcome": "STOP", "hit": "STOP", "hit_price": stop, "hit_time": ts_text, "checked": checked, "note": "Aynı mumda TP ve stop görüldü; güvenli hesapla stop önce kabul edildi."}
            if stop_hit:
                return {"outcome": "STOP", "hit": "STOP", "hit_price": stop, "hit_time": ts_text, "checked": checked, "note": "Stop mum taramasında önce geldi."}
            if tp3_hit:
                return {"outcome": "TP3", "hit": "TP3", "hit_price": tp3, "hit_time": ts_text, "checked": checked, "note": "TP3 mum taramasında stop öncesi geldi."}
            if tp2_hit:
                return {"outcome": "TP2", "hit": "TP2", "hit_price": tp2, "hit_time": ts_text, "checked": checked, "note": "TP2 mum taramasında stop öncesi geldi."}
            if tp1_hit:
                return {"outcome": "TP1", "hit": "TP1", "hit_price": tp1, "hit_time": ts_text, "checked": checked, "note": "TP1 mum taramasında stop öncesi geldi."}

    last_close = safe_float(klines[-1][4]) if klines else entry
    pnl_pct = pct_change(entry, last_close) if direction == "LONG" else pct_change(entry, last_close) * -1
    return {"outcome": "NO_HIT", "hit": "YOK", "hit_price": last_close, "hit_time": tr_str(), "checked": checked, "pnl_pct": round(pnl_pct, 2), "note": "Takip süresinde TP/stop görülmedi; sadece güncel PnL yazıldı."}

async def followup_loop() -> None:
    while True:
        try:
            follows = memory.get("follows", {})
            if not follows:
                await asyncio.sleep(FOLLOWUP_CHECK_INTERVAL_SEC)
                continue
            now_ts = time.time()
            for key, rec in list(follows.items()):
                if rec.get("done"):
                    continue
                sent_ts = safe_float(rec.get("sent_ts", 0))
                if now_ts - sent_ts < FOLLOWUP_DELAY_SEC:
                    continue

                sym = normalize_symbol(str(rec.get("symbol", key)).replace("LONG:", "").replace("SHORT:", ""))
                direction = str(rec.get("direction", "SHORT")).upper()
                entry = safe_float(rec.get("entry", 0))
                stop = safe_float(rec.get("stop", 0))
                tp1 = safe_float(rec.get("tp1", 0))
                tp2 = safe_float(rec.get("tp2", 0))
                tp3 = safe_float(rec.get("tp3", 0))
                if entry <= 0:
                    continue

                k1 = await get_klines(sym, "1m", 180)
                if not k1:
                    continue

                result = evaluate_tp_stop_path(k1, direction, sent_ts, entry, stop, tp1, tp2, tp3)
                cur = safe_float(k1[-1][4])
                pnl_pct = pct_change(entry, cur) if direction == "LONG" else pct_change(entry, cur) * -1
                outcome = str(result.get("outcome", "NO_HIT"))
                hit_price = safe_float(result.get("hit_price", cur))
                hit_time = str(result.get("hit_time", "-"))

                if outcome.startswith("TP"):
                    title = f"✅ {outcome} GELDİ"
                elif outcome == "STOP":
                    title = "❌ STOP GELDİ"
                else:
                    title = "⏳ TP/STOP YOK"

                pm_note = position_management_summary(k1, direction, entry, stop, tp1, tp2, tp3)
                if outcome == "STOP":
                    learn_from_stopped_signal(sym, direction, rec, result)
                else:
                    stats["position_management_updates"] = stats.get("position_management_updates", 0) + 1

                text = (
                    f"⏱ 2 SAAT TP/STOP TAKİP\n"
                    f"{title}\n"
                    f"⏰ Rapor: {tr_str()} | İlk temas: {hit_time}\n"
                    f"🎯 {sym} | {direction}\n"
                    f"💰 Giriş: {fmt_num(entry)} | Güncel: {fmt_num(cur)}\n"
                    f"📍 Sonuç fiyatı: {fmt_num(hit_price)}\n"
                    f"📊 Güncel PnL: %{pnl_pct:.2f}\n"
                    f"🛑 Stop: {fmt_num(stop)}\n"
                    f"🎯 TP1: {fmt_num(tp1)} | TP2: {fmt_num(tp2)} | TP3: {fmt_num(tp3)}\n"
                    f"🧭 Mum tarama: {result.get('checked', 0)} adet 1m mum incelendi.\n"
                    f"📌 Pozisyon yönetimi: {pm_note}\n"
                    f"Not: {result.get('note', '-')}"
                )
                ok = await safe_send_telegram(text)
                if ok:
                    stats["followup_sent"] += 1
                    rec["done"] = True
                    rec["outcome"] = outcome
                    rec["hit_price"] = hit_price
                    rec["hit_time"] = hit_time
                    rec["final_price"] = cur
                    rec["pnl_pct"] = round(pnl_pct, 2)
        except Exception as e:
            logger.exception("followup_loop hata: %s", e)
        await asyncio.sleep(max(60, FOLLOWUP_CHECK_INTERVAL_SEC))


async def save_loop() -> None:
    while True:
        try:
            save_memory()
        except Exception as e:
            logger.exception("save_loop hata: %s", e)
        await asyncio.sleep(max(20, MEMORY_SAVE_INTERVAL_SEC))


# =========================================================
# TELEGRAM KOMUTLARI
# =========================================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"🐋 {VERSION_NAME} AKTİF\n\n"
        "Komutlar:\n"
        "/status - Durum raporu\n"
        "/hot - Sıcak coinler\n"
        "/trend - Trend izleme listesi\n"
        "/coin BTCUSDT - Tek coin analiz\n"
        "/scan - Hızlı tarama\n"
        "/whale BTCUSDT - Whale Eye detay\n"
        "/av - Görünmeyen yüz av listesi\n"
        "/ws - WebSocket durumu\n"
        "/hafiza - Hata hafızası\n"
        "/backtest BTCUSDT SHORT 240 - Maliyetli replay backtest\n"
        "/pozisyon - Aktif takip\n"
        "/test - Test mesajı\n"
        "/id - Chat ID göster\n\n"
        "V6 YENİ MOTORLAR:\n"
        "🐋 Open Interest Delta\n"
        "💰 Funding Rate Dedektörü\n"
        "🪤 Orderbook Spoofing\n"
        "📊 CVD Diverjans\n"
        "📡 WebSocket orderbook/trade\n"
        "🧱 Destek/direnç final kapısı\n"
        "🧠 Hata hafızası\n"
        "🧪 Maliyetli backtest"
    )


async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ok = await safe_send_telegram(f"✅ Test başarılı. {tr_str()}")
    await update.message.reply_text("Test gönderildi." if ok else "Test başarısız.")


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    await update.message.reply_text(f"CHAT ID: {chat.id}\nTYPE: {chat.type}\nTITLE: {chat.title or chat.first_name or '-'}")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(build_heartbeat_message())


async def cmd_hot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    hot = memory.get("hot", {})
    if not hot:
        await update.message.reply_text("Şu an sıcak coin yok.")
        return
    items = sorted(hot.items(), key=lambda x: safe_float(x[1].get("score", 0)), reverse=True)[:10]
    lines = ["🔥 Sıcak Coinler:"]
    for sym, rec in items:
        lines.append(f"- {sym} | skor={safe_float(rec.get('score', 0)):.1f} | 🐋={rec.get('whale_confidence', '-')} | fiyat={fmt_num(safe_float(rec.get('last_price', 0)))}")
    await update.message.reply_text("\n".join(lines))


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tickers24 = await get_24h_tickers()
    syms = pick_general_symbols(8)
    out = ["🔎 Hızlı Tarama:"]
    for sym in syms:
        res = await analyze_symbol(sym, tickers24)
        if not res:
            continue
        whale_conf = res.get("whale_eye", {}).get("whale_confidence", "-")
        out.append(f"- {sym} | {res['stage']} | skor={res.get('score', 0)} | 🐋={whale_conf} | fiyat={fmt_num(safe_float(res.get('price', 0)))}")
    await update.message.reply_text("\n".join(out[:25]))


async def cmd_coin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Kullanım: /coin BTCUSDT")
        return
    symbol = normalize_symbol(context.args[0])
    tickers24 = await get_24h_tickers()
    res = await analyze_symbol(symbol, tickers24)
    if not res:
        await update.message.reply_text(f"{symbol} analiz edilemedi.")
        return
    if res["stage"] == "SIGNAL":
        confirm = await confirm_signal_on_binance(res)
        res["data_engine"] = "OKX SWAP"
        res["binance_confirm_status"] = confirm.get("status", "YOK")
        res["binance_symbol"] = confirm.get("binance_symbol", "")
        res["binance_price"] = confirm.get("binance_price", 0)
        res["binance_price_gap_pct"] = confirm.get("price_gap_pct", 0)
        res["binance_confirm_reason"] = confirm.get("reason", "-")
        await update.message.reply_text(build_signal_message(res))
    elif res["stage"] == "READY":
        await update.message.reply_text(build_ready_message(res))
    elif res["stage"] == "HOT":
        await update.message.reply_text(build_hot_message(res))
    else:
        await update.message.reply_text(f"{symbol} şu an short için zayıf.\nSkor: {res.get('score', 0)}\n🐋 Whale: {res.get('whale_eye', {}).get('whale_confidence', '-')}\n{res.get('reason', '')[:300]}")


async def cmd_whale(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Whale Eye detaylı raporu"""
    if not context.args:
        await update.message.reply_text("Kullanım: /whale BTCUSDT")
        return
    symbol = normalize_symbol(context.args[0])
    k1 = await get_klines(symbol, "1m", 120)
    if len(k1) < 50:
        await update.message.reply_text(f"{symbol} için yeterli veri yok.")
        return
    price = safe_float(k1[-1][4])
    whale = await build_full_whale_eye_analysis(symbol, price, 0, k1, "SHORT")

    oi = whale.get("oi", {})
    funding = whale.get("funding", {})
    spoofing = whale.get("spoofing", {})
    cvd = whale.get("cvd", {})

    msg = (
        f"🐋 WHALE EYE RAPORU - {symbol}\n"
        f"⏰ {tr_str()}\n"
        f"💰 Fiyat: {fmt_num(price)}\n"
        f"📊 Toplam Skor: {whale.get('total_score', 0)}\n"
        f"🎯 Güven: {whale.get('whale_confidence', '-')}\n"
        f"🔢 Uyumsuzluk: {whale.get('divergence_count', 0)}\n\n"
        f"📈 OPEN INTEREST\n"
        f"├─ Durum: {oi.get('divergence_type', '-')}\n"
        f"├─ Güncel OI: {oi.get('current_oi', 0):,.0f}\n"
        f"├─ OI Değişim: %{oi.get('oi_change_pct', 0):.2f}\n"
        f"└─ Fiyat Değişim: %{oi.get('price_change_pct', 0):.2f}\n\n"
        f"💰 FUNDING RATE\n"
        f"├─ Oran: %{funding.get('funding_rate', 0):.4f}\n"
        f"├─ Sinyal: {funding.get('funding_signal', '-')}\n"
        f"└─ Yorum: {funding.get('reason', '-')}\n\n"
        f"🪤 ORDERBOOK SPOOFING\n"
        f"├─ Tespit: {spoofing.get('spoofing_detected', False)}\n"
        f"├─ Tip: {spoofing.get('spoof_type', '-')}\n"
        f"└─ Yorum: {spoofing.get('reason', '-')}\n\n"
        f"📊 CVD\n"
        f"├─ Diverjans: {cvd.get('divergence', '-')}\n"
        f"├─ CVD Trend: %{cvd.get('cvd_trend_pct', 0):.2f}\n"
        f"└─ Fiyat Trend: %{cvd.get('price_trend_pct', 0):.2f}"
    )
    await update.message.reply_text(msg)


async def cmd_trend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    trend_watch = memory.get("trend_watch", {})
    if not trend_watch:
        await update.message.reply_text("Şu an trend devam kilidine takılan coin yok.")
        return

    items = sorted(
        trend_watch.items(),
        key=lambda x: safe_float(x[1].get("score", 0)),
        reverse=True
    )[:12]

    lines = ["🧲 Trend izleme / short erken kilidi:"]
    for sym, rec in items:
        first_price = safe_float(rec.get("first_price", 0))
        last_price = safe_float(rec.get("last_price", 0))
        move = pct_change(first_price, last_price) if first_price > 0 and last_price > 0 else 0.0
        whale_conf = rec.get("whale_confidence", "-")
        lines.append(
            f"- {sym} | skor={safe_float(rec.get('score', 0)):.1f} | 🐋={whale_conf} | "
            f"ilk={fmt_num(first_price)} | son={fmt_num(last_price)} | "
            f"hareket=%{move:.2f} | kırılım={safe_float(rec.get('breakdown_score', 0)):.1f}"
        )

    await update.message.reply_text("\n".join(lines))


async def cmd_av(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    merged: Dict[str, Dict[str, Any]] = {}
    for sym, rec in memory.get("hot", {}).items():
        merged[sym] = {**copy.deepcopy(rec), "source": "HOT"}
    for sym, rec in memory.get("trend_watch", {}).items():
        old = merged.get(sym, {})
        if safe_float(rec.get("score", 0)) > safe_float(old.get("score", 0)):
            merged[sym] = {**copy.deepcopy(rec), "source": "TREND"}
    if not merged:
        await update.message.reply_text("🎯 Şu an av listesinde coin yok.")
        return
    items = sorted(merged.items(), key=lambda x: safe_float(x[1].get("score", 0)), reverse=True)[:15]
    lines = ["🎯 AV LİSTESİ:"]
    for sym, rec in items:
        lines.append(f"- {sym} | skor={safe_float(rec.get('score', 0)):.1f} | 🐋={rec.get('whale_confidence', '-')} | fiyat={fmt_num(safe_float(rec.get('last_price', 0)))}")
    await update.message.reply_text("\n".join(lines))


# =========================================================
# BAŞLATMA
# =========================================================
async def post_init(application) -> None:
    active_count, pruned_count = await refresh_coin_pool(force=True)
    await init_professional_crypto_ai_embedded()

    if AUTO_START_MESSAGE:
        await safe_send_telegram(
            f"🐋 {VERSION_NAME} BAŞLADI\n"
            f"⏰ {tr_str()}\n"
            f"📊 Coin: {active_count} aktif\n"
            f"🗑️ Çıkarılan: {pruned_count}\n"
            f"📡 Veri: OKX {OKX_INST_TYPE}\n"
            f"🐋 Whale Eye: OI + Funding + Spoofing + CVD AKTİF\n"
            f"🎯 Günlük SHORT limit: {DAILY_SHORT_TOTAL_LIMIT}\n"
            f"🎯 Günlük LONG limit: {LONG_DAILY_TOTAL_LIMIT}"
        )

    asyncio.create_task(okx_public_ws_loop())
    asyncio.create_task(hot_scan_loop())
    asyncio.create_task(deep_scan_loop())
    asyncio.create_task(ai_auto_signal_loop())
    asyncio.create_task(symbol_refresh_loop())
    asyncio.create_task(heartbeat_loop())
    asyncio.create_task(followup_loop())
    asyncio.create_task(save_loop())
    logger.info("Tüm motorlar başlatıldı")


def validate_config() -> None:
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")
    if missing:
        raise RuntimeError(f"Eksik env: {', '.join(missing)}")



async def cmd_ws(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    age = time.time() - safe_float(ws_runtime_state.get("last_msg_ts", 0)) if ws_runtime_state.get("last_msg_ts") else 9999
    sample = list(ws_orderbooks.keys())[:10]
    await update.message.reply_text(
        "📡 WEBSOCKET DURUM\n"
        f"Aktif: {PRO_WS_ENABLED} | Paket: {websockets is not None}\n"
        f"URL: {PRO_WS_URL}\n"
        f"Kanal: {PRO_WS_BOOK_CHANNEL} + {PRO_WS_TRADE_CHANNEL}\n"
        f"Book sembol: {len(ws_orderbooks)} | Trade kayıt: {sum(len(v) for v in ws_trades.values())}\n"
        f"Son mesaj yaşı: {age:.1f}s | Reconnect: {ws_runtime_state.get('reconnects', 0)}\n"
        f"Örnek semboller: {', '.join(sample) if sample else '-'}\n"
        f"Son hata: {ws_runtime_state.get('last_error', '-')}"
    )


async def cmd_hafiza(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    mm = memory.get("mistake_memory", {}) or {}
    patterns = mm.get("patterns", {}) if isinstance(mm, dict) else {}
    if not patterns:
        await update.message.reply_text("🧠 Hata hafızası boş. Stop olan sinyal geldikçe pattern öğrenir.")
        return
    items = sorted(patterns.items(), key=lambda x: safe_float((x[1] or {}).get("last_ts", 0)), reverse=True)[:10]
    lines = ["🧠 HATA HAFIZASI"]
    for sig, rec in items:
        lines.append(f"- stop={rec.get('stops', 0)} | {rec.get('last_symbol', '-')} | {tr_str(safe_float(rec.get('last_ts', 0)))}\n  {sig}")
    await update.message.reply_text("\n".join(lines)[:3900])


def _nl_clean_text(text: str) -> str:
    import re
    s = (text or "").strip().lower()
    tr_map = str.maketrans({"ç":"c","ğ":"g","ı":"i","ö":"o","ş":"s","ü":"u","â":"a","î":"i","û":"u"})
    s = s.translate(tr_map)
    s = re.sub(r"[^a-z0-9\s\-_/\.]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _nl_coin_list_message() -> str:
    shown = COINS[:45]
    extra = len(COINS) - len(shown)
    return f"📋 AKTİF COIN LİSTESİ ({len(COINS)})\n" + ", ".join(shown) + (f"\n+{extra} coin daha" if extra > 0 else "")


def _nl_extract_coin(text_raw: str) -> Optional[str]:
    cleaned = _nl_clean_text(text_raw).upper().replace("/", "-")
    known = {coin_base_from_symbol(x): normalize_symbol(x) for x in COINS}
    for token in cleaned.replace("-", " ").split():
        if token in known:
            return known[token]
        if token.endswith("USDT") and len(token) > 4:
            return normalize_symbol(token)
    return None


async def cmd_natural(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    txt_raw = update.message.text or ""
    txt = _nl_clean_text(txt_raw)
    if not txt:
        return
    stats["natural_language_hit"] = stats.get("natural_language_hit", 0) + 1
    if any(x in txt for x in ("durum", "calisiyor", "ayakta", "bot ne durumda")):
        await cmd_status(update, context); return
    if any(x in txt for x in ("websocket", "ws", "canli veri", "orderbook")):
        await cmd_ws(update, context); return
    if any(x in txt for x in ("hafiza", "hata hafizasi", "stop hatasi")):
        await cmd_hafiza(update, context); return
    if any(x in txt for x in ("hangi coin", "coin listesi", "coinleri", "izliyorsun", "aktif coin")) and not _nl_extract_coin(txt_raw):
        await update.message.reply_text(_nl_coin_list_message()); return
    if "short" in txt and any(x in txt for x in ("var", "sinyal", "firsat")):
        await update.message.reply_text(f"📨 SHORT: bugün {get_today_short_sent_count()}/{DAILY_SHORT_TOTAL_LIMIT}. Yeni temiz SHORT oluşursa otomatik gelir."); return
    if "long" in txt and any(x in txt for x in ("var", "sinyal", "firsat")):
        await update.message.reply_text(f"📨 LONG: bugün {get_today_long_sent_count()}/{LONG_DAILY_TOTAL_LIMIT}. Yeni temiz LONG oluşursa otomatik gelir."); return
    if any(x in txt for x in ("sicak", "hot")):
        await cmd_hot(update, context); return
    if any(x in txt for x in ("balina", "whale", "funding", "cvd", "spoof")) or "oi" in set(txt.split()):
        sym = _nl_extract_coin(txt_raw) or "BTC-USDT-SWAP"
        context.args = [sym]
        await cmd_whale(update, context); return
    sym = _nl_extract_coin(txt_raw)
    if sym and any(x in txt for x in ("bak", "analiz", "ne durumda", "coin")):
        context.args = [sym]
        await cmd_coin(update, context); return
    await update.message.reply_text("Duydum dostum. Şunları yazabilirsin: durum ne, ws çalışıyor mu, short var mı, btc balina bak, sei bak, hangi coinleri izliyorsun, hata hafızası.")


async def run_costed_backtest(symbol: str, direction: str, bars: int) -> str:
    symbol = normalize_symbol(symbol)
    direction = (direction or "SHORT").upper()
    k1 = await get_klines(symbol, "1m", min(max(bars, 80), 300))
    if len(k1) < 60:
        return f"{symbol} backtest için veri yetersiz."
    wins = losses = no_hit = 0
    equity = 100.0
    max_eq = equity
    max_dd = 0.0
    trades = 0
    for i in range(30, len(k1)-20, 10):
        entry = safe_float(k1[i][4])
        if entry <= 0:
            continue
        sub_h = highs(k1[max(0, i-30):i+1]); sub_l = lows(k1[max(0, i-30):i+1])
        a = atr(k1[max(0, i-40):i+1], 14)
        last_atr = max(a[-1], entry*0.0015) if a else entry*0.0015
        if direction == "LONG":
            stop, tp1, tp2, tp3, rr = calculate_long_levels(entry, sub_l, last_atr, last_atr)
        else:
            stop, tp1, tp2, tp3, rr = calculate_short_levels(entry, sub_h, last_atr, last_atr)
        res = evaluate_tp_stop_path(k1[i+1:i+21], direction, 0, entry, stop, tp1, tp2, tp3)
        outcome = res.get("outcome")
        trades += 1
        cost = BACKTEST_FEE_PCT + BACKTEST_SLIPPAGE_PCT + (BACKTEST_FUNDING_PCT_PER_8H / 4.0)
        if outcome and str(outcome).startswith("TP"):
            wins += 1
            hit = safe_float(res.get("hit_price", tp1))
            gross = pct_change(entry, hit) if direction == "LONG" else pct_change(entry, hit) * -1
            equity *= (1 + (gross - cost) / 100.0)
        elif outcome == "STOP":
            losses += 1
            hit = safe_float(res.get("hit_price", stop))
            gross = pct_change(entry, hit) if direction == "LONG" else pct_change(entry, hit) * -1
            equity *= (1 + (gross - cost) / 100.0)
        else:
            no_hit += 1
            equity *= (1 - cost / 100.0)
        max_eq = max(max_eq, equity)
        dd = (max_eq - equity) / max(max_eq, 1e-9) * 100.0
        max_dd = max(max_dd, dd)
    stats["backtest_runs"] = stats.get("backtest_runs", 0) + 1
    stats["backtest_cost_applied"] = stats.get("backtest_cost_applied", 0) + trades
    wr = wins / max(wins+losses, 1) * 100.0
    return (
        f"🧪 MALİYETLİ BACKTEST / REPLAY\n"
        f"Coin: {symbol} | Yön: {direction} | Mum: {len(k1)}\n"
        f"İşlem: {trades} | TP: {wins} | Stop: {losses} | No hit: {no_hit} | WR: %{wr:.1f}\n"
        f"Final equity: {equity:.2f} | Max DD: %{max_dd:.2f}\n"
        f"Maliyet: fee %{BACKTEST_FEE_PCT} + slip %{BACKTEST_SLIPPAGE_PCT} + funding tahmini.\n"
        f"Not: Bu canlı motorun birebir kurumsal backtesti değil; maliyetli TP/stop yol replay testidir."
    )


async def cmd_backtest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await update.message.reply_text("Kullanım: /backtest BTCUSDT SHORT 240")
        return
    sym = normalize_symbol(args[0])
    direction = "LONG" if any(str(a).upper() == "LONG" for a in args[1:]) else "SHORT"
    nums = [int(str(a)) for a in args[1:] if str(a).isdigit()]
    bars = nums[-1] if nums else BACKTEST_DEFAULT_BARS
    await update.message.reply_text(await run_costed_backtest(sym, direction, bars))


async def cmd_pozisyon(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    follows = memory.get("follows", {}) or {}
    active = [r for r in follows.values() if not r.get("done")]
    if not active:
        await update.message.reply_text("📌 Aktif takipte pozisyon yok.")
        return
    lines = ["📌 AKTİF TAKİP / POZİSYON"]
    for r in active[:12]:
        lines.append(f"- {r.get('symbol')} {r.get('direction')} | entry={fmt_num(safe_float(r.get('entry',0)))} stop={fmt_num(safe_float(r.get('stop',0)))} TP1={fmt_num(safe_float(r.get('tp1',0)))}")
    await update.message.reply_text("\n".join(lines))


def build_app():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("test", cmd_test))
    application.add_handler(CommandHandler("id", cmd_id))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("health", cmd_status))
    application.add_handler(CommandHandler("scan", cmd_scan))
    application.add_handler(CommandHandler("coin", cmd_coin))
    application.add_handler(CommandHandler("hot", cmd_hot))
    application.add_handler(CommandHandler("whale", cmd_whale))
    application.add_handler(CommandHandler("trend", cmd_trend))
    application.add_handler(CommandHandler("av", cmd_av))
    application.add_handler(CommandHandler("ws", cmd_ws))
    application.add_handler(CommandHandler("hafiza", cmd_hafiza))
    application.add_handler(CommandHandler("backtest", cmd_backtest))
    application.add_handler(CommandHandler("pozisyon", cmd_pozisyon))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_natural))
    # Profesyonel AI komutları ana bot seviyesinde garanti eklenir.
    # Böylece embedded handler yüklenmese bile /ai_durum sessiz kalmaz.
    application.add_handler(CommandHandler("ai_durum", cmd_ai_durum_direct))
    application.add_handler(CommandHandler("zeka", cmd_zeka_direct))
    application.add_handler(CommandHandler("arastir", cmd_arastir_direct))
    application.add_handler(CommandHandler("yon", cmd_yon_direct))
    # Eski embedded ekleyici de çalışabilir; aynı komut varsa ana direct handler ilk yakalar.
    add_professional_ai_handlers_embedded(application)
    return application


async def shutdown_app(signal_type=None):
    logger.info("Shutdown başlatılıyor... (signal: %s)", signal_type)
    await shutdown_professional_crypto_ai_embedded()
    save_memory()
    logger.info("Memory kaydedildi.")
    if app:
        try:
            await app.stop()
            await app.shutdown()
        except Exception as e:
            logger.warning("Uygulama durdurma hatası: %s", e)
    logger.info("Bot durdu.")


def main() -> None:
    try:
        validate_config()
        load_memory()
        global app
        app = build_app()
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown_app(s.name)))
        logger.info("%s başlıyor", VERSION_NAME)
        app.run_polling(close_loop=False, drop_pending_updates=True)
    except KeyboardInterrupt:
        logger.info("Kullanıcı tarafından durduruldu.")
    except Exception as e:
        logger.exception("Kritik hata: %s", e)
        raise
    finally:
        logger.info("Memory kaydediliyor...")
        save_memory()
        logger.info("Bot durdu.")


if __name__ == "__main__":
    main()
