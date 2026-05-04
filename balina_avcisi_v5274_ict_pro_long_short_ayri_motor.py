import signal
import copy
import os
import json
import time
import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# =========================================================
# BALINA AVCISI V5.2.7.1 HIBRIT ONAYLI PARA KORUMALI - TEK PARCA SURUM
# Temel: V5.2.7 HIBRIT ONAYLI karakteri + paylaşılan dosyanın çalışan altyapısı
#
# Amaç:
# - V5.2.7'nin fırsat yakalama karakteri korunur
# - Toplu AL basma kesilir; aynı taramada en iyi aday seçilir
# - Günlük limit kota değildir, yalnızca üst sınırdır
# - Fırsat yoksa sinyal göndermez
# - Trend devam ederken kör SHORT atmaz, sessiz takip eder
# - Stoplar son fitil/ATR yapısına göre daha güvenli kurulur
# - 50$ sermaye için tek işlem / az işlem para koruma mantığı eklenir
#
# Uyarı:
# Bu bot kesin kazanç garantisi vermez. Gerçek para öncesi kağıt üstünde test et.
# =========================================================

VERSION_NAME = "Balina Avcısı V5.2.7.4 ICT PRO LONG/SHORT AYRI MOTOR"

# -------------------------
# ENV / AYARLAR
# -------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

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

MEMORY_FILE = os.getenv("MEMORY_FILE", "balina_avcisi_v5272_para_korumali_memory.json").strip()
LOG_FILE = os.getenv("LOG_FILE", "balina_avcisi_v5272_para_korumali.log").strip()
TIMEZONE_NAME = os.getenv("TIMEZONE_NAME", "Europe/Istanbul").strip()

AUTO_START_MESSAGE = os.getenv("AUTO_START_MESSAGE", "false").lower() == "true"
AUTO_HEARTBEAT = os.getenv("AUTO_HEARTBEAT", "false").lower() == "true"
AUTO_HOT_RISE_UPDATE = os.getenv("AUTO_HOT_RISE_UPDATE", "false").lower() == "true"
HEARTBEAT_INTERVAL_SEC = int(float(os.getenv("HEARTBEAT_INTERVAL_SEC", "7200")))
HOT_SCAN_INTERVAL_SEC = float(os.getenv("HOT_SCAN_INTERVAL_SEC", "1.5"))
DEEP_SCAN_INTERVAL_SEC = float(os.getenv("DEEP_SCAN_INTERVAL_SEC", "2"))
MEMORY_SAVE_INTERVAL_SEC = int(float(os.getenv("MEMORY_SAVE_INTERVAL_SEC", "60")))
FOLLOWUP_CHECK_INTERVAL_SEC = int(float(os.getenv("FOLLOWUP_CHECK_INTERVAL_SEC", "300")))
FOLLOWUP_DELAY_SEC = int(float(os.getenv("FOLLOWUP_DELAY_SEC", "7200")))
HOT_TTL_SEC = int(float(os.getenv("HOT_TTL_SEC", "1800")))
ALERT_COOLDOWN_MIN = int(float(os.getenv("ALERT_COOLDOWN_MIN", "180")))
SETUP_COOLDOWN_MIN = int(float(os.getenv("SETUP_COOLDOWN_MIN", "120")))
MAX_HOT_CANDIDATES = int(float(os.getenv("MAX_HOT_CANDIDATES", "16")))
MAX_DEEP_ANALYSIS_PER_CYCLE = int(float(os.getenv("MAX_DEEP_ANALYSIS_PER_CYCLE", "25")))

# V5.2.7.1 para korumalı ayar: V5.2.7 avcılığını bozma, spamı kes
MIN_CANDIDATE_SCORE = float(os.getenv("MIN_CANDIDATE_SCORE", "27"))
MIN_READY_SCORE = float(os.getenv("MIN_READY_SCORE", "44"))
MIN_SIGNAL_SCORE = float(os.getenv("MIN_SIGNAL_SCORE", "62"))
MIN_VERIFY_SCORE_FOR_SIGNAL = float(os.getenv("MIN_VERIFY_SCORE_FOR_SIGNAL", "22"))
MIN_QUALITY_SCORE = float(os.getenv("MIN_QUALITY_SCORE", "4.5"))
DAILY_SHORT_TOTAL_LIMIT = int(float(os.getenv("DAILY_SHORT_TOTAL_LIMIT", "7")))
MAX_SIGNAL_PER_SCAN = int(float(os.getenv("MAX_SIGNAL_PER_SCAN", "1")))
SIGNAL_SPACING_SEC = int(float(os.getenv("SIGNAL_SPACING_SEC", "0")))
ONE_ACTIVE_TRADE_MODE = os.getenv("ONE_ACTIVE_TRADE_MODE", "false").lower() == "true"
ACTIVE_TRADE_BLOCK_SEC = int(float(os.getenv("ACTIVE_TRADE_BLOCK_SEC", "0")))

SCORE_OVERRIDE_GAP = float(os.getenv("SCORE_OVERRIDE_GAP", "12"))
PRICE_OVERRIDE_MOVE_PCT = float(os.getenv("PRICE_OVERRIDE_MOVE_PCT", "0.90"))

NO_SIGNAL_DIAG_SEC = int(float(os.getenv("NO_SIGNAL_DIAG_SEC", "999999")))

KLINE_CACHE_SEC = int(float(os.getenv("KLINE_CACHE_SEC", "12")))
TICKER_CACHE_SEC = int(float(os.getenv("TICKER_CACHE_SEC", "8")))
HTTP_TIMEOUT = int(float(os.getenv("HTTP_TIMEOUT", "12")))

# Veri koruma katmani
OKX_INSTRUMENT_CACHE_SEC = int(float(os.getenv("OKX_INSTRUMENT_CACHE_SEC", "1800")))
AUTO_SYMBOL_REFRESH_SEC = int(float(os.getenv("AUTO_SYMBOL_REFRESH_SEC", "1800")))
SYMBOL_FAIL_BLOCK_SEC = int(float(os.getenv("SYMBOL_FAIL_BLOCK_SEC", "900")))
SYMBOL_FAIL_FORGET_SEC = int(float(os.getenv("SYMBOL_FAIL_FORGET_SEC", "43200")))
SYMBOL_FAIL_MAX_STREAK = int(float(os.getenv("SYMBOL_FAIL_MAX_STREAK", "2")))

MIN_24H_QUOTE_VOLUME = float(os.getenv("MIN_24H_QUOTE_VOLUME", "1200000"))

# Trend koruma
TREND_GUARD_ENABLED = os.getenv("TREND_GUARD_ENABLED", "true").lower() == "true"
TREND_GUARD_MIN_PUMP_10M = float(os.getenv("TREND_GUARD_MIN_PUMP_10M", "0.90"))
TREND_GUARD_MIN_PUMP_20M = float(os.getenv("TREND_GUARD_MIN_PUMP_20M", "1.35"))
TREND_GUARD_MIN_RSI_1M = float(os.getenv("TREND_GUARD_MIN_RSI_1M", "58"))
TREND_GUARD_MIN_RSI_5M = float(os.getenv("TREND_GUARD_MIN_RSI_5M", "57"))
TREND_GUARD_SCORE_BLOCK = float(os.getenv("TREND_GUARD_SCORE_BLOCK", "5"))
TREND_BREAKDOWN_MIN_SCORE = float(os.getenv("TREND_BREAKDOWN_MIN_SCORE", "7.2"))
TREND_WATCH_TTL_SEC = int(float(os.getenv("TREND_WATCH_TTL_SEC", "3600")))
MIN_RED_CANDLES_FOR_SHORT = int(float(os.getenv("MIN_RED_CANDLES_FOR_SHORT", "2")))

# Stop / hedef
SHORT_STOP_ATR_MULT = float(os.getenv("SHORT_STOP_ATR_MULT", "2.20"))
SHORT_STOP_WICK_ATR_BUFFER = float(os.getenv("SHORT_STOP_WICK_ATR_BUFFER", "0.55"))
SHORT_MIN_STOP_PCT = float(os.getenv("SHORT_MIN_STOP_PCT", "0.55"))
SHORT_MAX_STOP_PCT = float(os.getenv("SHORT_MAX_STOP_PCT", "3.10"))
SHORT_TP1_R_MULT = float(os.getenv("SHORT_TP1_R_MULT", "1.20"))
SHORT_TP2_R_MULT = float(os.getenv("SHORT_TP2_R_MULT", "1.75"))
SHORT_TP3_R_MULT = float(os.getenv("SHORT_TP3_R_MULT", "2.55"))
MIN_RR_TP1 = float(os.getenv("MIN_RR_TP1", "1.05"))

# Kırılım destekli aday motoru
BREAKDOWN_ASSIST_ENABLED = os.getenv("BREAKDOWN_ASSIST_ENABLED", "true").lower() == "true"
BREAKDOWN_ASSIST_MIN_SCORE = float(os.getenv("BREAKDOWN_ASSIST_MIN_SCORE", "6.6"))
BREAKDOWN_ASSIST_STRONG_SCORE = float(os.getenv("BREAKDOWN_ASSIST_STRONG_SCORE", "8.6"))
BREAKDOWN_ASSIST_CANDIDATE_FLOOR = float(os.getenv("BREAKDOWN_ASSIST_CANDIDATE_FLOOR", "28"))
BREAKDOWN_ASSIST_READY_FLOOR = float(os.getenv("BREAKDOWN_ASSIST_READY_FLOOR", "48"))
BREAKDOWN_ASSIST_VERIFY_BONUS = float(os.getenv("BREAKDOWN_ASSIST_VERIFY_BONUS", "3"))
BREAKDOWN_ASSIST_STRONG_VERIFY_BONUS = float(os.getenv("BREAKDOWN_ASSIST_STRONG_VERIFY_BONUS", "5"))

# Görünmeyen yüz / likidite avı motoru
# Not: Bu motor balinayı ismen bilmez; public OKX verisinden iz okur:
# likidite süpürme, stop hunt, alıcı/satıcı tuzağı, orderbook duvar değişimi,
# agresif trade flow, dağıtım ve işlem alınabilirlik.
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

# Tepe erken para çıkışı modu
# Amaç: düşüş bittikten sonra değil, pump sonrası tepe bölgesinde para çıkışı başlarken haber vermek.
TEPE_ERKEN_MOD_ENABLED = os.getenv("TEPE_ERKEN_MOD_ENABLED", "true").lower() == "true"
TEPE_ERKEN_MIN_PUMP_20M = float(os.getenv("TEPE_ERKEN_MIN_PUMP_20M", "0.85"))
TEPE_ERKEN_MIN_PUMP_1H = float(os.getenv("TEPE_ERKEN_MIN_PUMP_1H", "1.20"))
TEPE_ERKEN_MIN_DROP_FROM_PEAK = float(os.getenv("TEPE_ERKEN_MIN_DROP_FROM_PEAK", "0.03"))
TEPE_ERKEN_MAX_DROP_FROM_PEAK = float(os.getenv("TEPE_ERKEN_MAX_DROP_FROM_PEAK", "1.05"))
TEPE_ERKEN_TOO_LATE_DROP = float(os.getenv("TEPE_ERKEN_TOO_LATE_DROP", "1.45"))
TEPE_ERKEN_MAX_PEAK_AGE_CANDLES = int(float(os.getenv("TEPE_ERKEN_MAX_PEAK_AGE_CANDLES", "14")))
TEPE_ERKEN_MIN_EXIT_SCORE = float(os.getenv("TEPE_ERKEN_MIN_EXIT_SCORE", "4.0"))
TEPE_ERKEN_BLOCK_LOCAL_LOW_BOUNCE = float(os.getenv("TEPE_ERKEN_BLOCK_LOCAL_LOW_BOUNCE", "0.25"))
TEPE_ERKEN_STRONG_SELL_TO_BUY = float(os.getenv("TEPE_ERKEN_STRONG_SELL_TO_BUY", "1.12"))
TEPE_ERKEN_STRONG_BUY_TO_SELL_BLOCK = float(os.getenv("TEPE_ERKEN_STRONG_BUY_TO_SELL_BLOCK", "2.20"))

# FIRSAT KAÇIRMA FIX
# Amaç: PENDLE/DYDX gibi pump-tepe-red fırsatlarını sadece WATCH'ta bırakmamak.
# Dışarı yine tek işlem mesajı gider: SHORT AL. Riskli/takip etiketleri Telegram'a AL olarak basılmaz.
INVISIBLE_FACE_PROMOTE_SIGNAL_ENABLED = os.getenv("INVISIBLE_FACE_PROMOTE_SIGNAL_ENABLED", "true").lower() == "true"
TEPE_ERKEN_PROMOTE_SIGNAL_ENABLED = os.getenv("TEPE_ERKEN_PROMOTE_SIGNAL_ENABLED", "true").lower() == "true"
TEPE_ERKEN_PROMOTE_MIN_INVISIBLE_SCORE = float(os.getenv("TEPE_ERKEN_PROMOTE_MIN_INVISIBLE_SCORE", "70"))
TEPE_ERKEN_PROMOTE_MIN_BREAKDOWN_SCORE = float(os.getenv("TEPE_ERKEN_PROMOTE_MIN_BREAKDOWN_SCORE", "3.0"))
TEPE_ERKEN_ALLOW_RISKY_CLOSE = os.getenv("TEPE_ERKEN_ALLOW_RISKY_CLOSE", "true").lower() == "true"

# Eski ayar ekranında FIRST_BREAK_* girildiyse artık boşa gitmez.
FIRST_BREAK_ENGINE_ENABLED = os.getenv("FIRST_BREAK_ENGINE_ENABLED", "true").lower() == "true"
FIRST_BREAK_MIN_SCORE = float(os.getenv("FIRST_BREAK_MIN_SCORE", "5.6"))
FIRST_BREAK_WATCH_SCORE = float(os.getenv("FIRST_BREAK_WATCH_SCORE", "4.0"))
FIRST_BREAK_MIN_BREAKDOWN_SCORE = float(os.getenv("FIRST_BREAK_MIN_BREAKDOWN_SCORE", "3.0"))
FIRST_BREAK_SELL_TAKEOVER_MIN = float(os.getenv("FIRST_BREAK_SELL_TAKEOVER_MIN", "0.82"))
FIRST_BREAK_BUY_WEAKENING_MAX = float(os.getenv("FIRST_BREAK_BUY_WEAKENING_MAX", "1.12"))

# Riskli TP1 scalp hedefleri normal SHORT hedefi gibi uzak tutulmaz.
# Bu sınıf temiz trend shortu değil; tepe sonrası hızlı al-kaç fırsatıdır.
# Varsayılan TP1 %0.45: TAO örneğinde 273.10 -> yaklaşık 271.87, yani 271.86 iğnesini yakalar.
RISKY_SCALP_CLOSE_TP_ENABLED = os.getenv("RISKY_SCALP_CLOSE_TP_ENABLED", "true").lower() == "true"
RISKY_SCALP_TP1_PCT = float(os.getenv("RISKY_SCALP_TP1_PCT", "0.45"))
RISKY_SCALP_TP2_PCT = float(os.getenv("RISKY_SCALP_TP2_PCT", "0.65"))
RISKY_SCALP_TP3_PCT = float(os.getenv("RISKY_SCALP_TP3_PCT", "0.90"))
RISKY_SCALP_MIN_RR_TP1 = float(os.getenv("RISKY_SCALP_MIN_RR_TP1", "0.35"))

# 5m/15m kapanış kapısı
# Amaç: bot saniyelik takip etsin, fakat 1 dakikalık yanıltıcı hareketle SHORT AL açtırmasın.
# 1m = erken radar / takip; 5m kapanış = işlem kapısı; 15m kapanış/yapı = ana onay.
CLOSE_CONFIRM_GATE_ENABLED = os.getenv("CLOSE_CONFIRM_GATE_ENABLED", "true").lower() == "true"
CLOSE_CONFIRM_REQUIRE_5M = os.getenv("CLOSE_CONFIRM_REQUIRE_5M", "true").lower() == "true"
CLOSE_CONFIRM_REQUIRE_15M = os.getenv("CLOSE_CONFIRM_REQUIRE_15M", "true").lower() == "true"
CLOSE_CONFIRM_MIN_5M_SCORE = float(os.getenv("CLOSE_CONFIRM_MIN_5M_SCORE", "4.2"))
CLOSE_CONFIRM_MIN_15M_SCORE = float(os.getenv("CLOSE_CONFIRM_MIN_15M_SCORE", "2.6"))
CLOSE_CONFIRM_CLEAN_5M_SCORE = float(os.getenv("CLOSE_CONFIRM_CLEAN_5M_SCORE", "6.1"))
CLOSE_CONFIRM_CLEAN_15M_SCORE = float(os.getenv("CLOSE_CONFIRM_CLEAN_15M_SCORE", "4.0"))


# =========================================================
# ICT + AYRI LONG MOTOR AYARLARI
# Not: SHORT motoru mevcut Balina Avcısı motoru olarak ayrı kalır.
# LONG motoru tamamen ayrı çalışır; tek motor iki yön vermez.
# =========================================================
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

# ICT PRO AYARLARI - tam bölge/yapı/likidite okuma
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
# Türkiye saati varsayımı: Londra açılış/NY açılış çevresi crypto için puan desteği, tek başına sinyal değildir.
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

# Kullanıcı kararı: PEPE/Pepe türevleri bu botun coin evreninden çıkarıldı.
# COINS env içine yanlışlıkla yazılsa bile bot havuza almaz.
BLOCKED_COIN_BASE_KEYWORDS = tuple(
    x.strip().upper()
    for x in os.getenv(
        "BLOCKED_COIN_BASE_KEYWORDS",
        "PEPE,1000PEPE,DOGE,SHIB,FLOKI,BONK,WIF,MEME,TURBO,MEW,BRETT,NOT,"
        "BOME,TRUMP,FARTCOIN,PNUT,GOAT,MELANIA,AI16Z,VINE,GRIFFAIN,PIPPIN"
    ).split(",")
    if x.strip()
)


# Temiz/bilindik coin listesi.
# Kirli meme/hype coinler çıkarıldı. OKX canlı listesi refresh_coin_pool ile ayrıca filtrelenir.
DEFAULT_COINS = [
    "XRP-USDT-SWAP", "ADA-USDT-SWAP", "TRX-USDT-SWAP", "XLM-USDT-SWAP",
    "HBAR-USDT-SWAP", "ALGO-USDT-SWAP", "VET-USDT-SWAP", "IOTA-USDT-SWAP",
    "CHZ-USDT-SWAP", "GALA-USDT-SWAP", "ZIL-USDT-SWAP", "ZRX-USDT-SWAP",
    "DYDX-USDT-SWAP", "SEI-USDT-SWAP", "ARB-USDT-SWAP", "OP-USDT-SWAP",
    "SAND-USDT-SWAP", "MANA-USDT-SWAP", "FLOW-USDT-SWAP", "ROSE-USDT-SWAP",
    "CFX-USDT-SWAP", "SKL-USDT-SWAP", "ANKR-USDT-SWAP", "CELR-USDT-SWAP",
    "IOST-USDT-SWAP", "ONE-USDT-SWAP", "SXP-USDT-SWAP", "CTSI-USDT-SWAP",
    "RSR-USDT-SWAP", "BLUR-USDT-SWAP", "ACH-USDT-SWAP", "API3-USDT-SWAP",
    "GMT-USDT-SWAP", "LRC-USDT-SWAP", "KAVA-USDT-SWAP", "MINA-USDT-SWAP",
    "WOO-USDT-SWAP", "BAND-USDT-SWAP", "STORJ-USDT-SWAP", "MASK-USDT-SWAP",
    "ID-USDT-SWAP", "ARPA-USDT-SWAP", "ONT-USDT-SWAP", "QTUM-USDT-SWAP",
    "BAT-USDT-SWAP", "ENJ-USDT-SWAP", "RVN-USDT-SWAP", "KNC-USDT-SWAP",
    "COMP-USDT-SWAP", "CRV-USDT-SWAP", "LDO-USDT-SWAP", "PENDLE-USDT-SWAP",
    "ENA-USDT-SWAP", "PYTH-USDT-SWAP", "JUP-USDT-SWAP", "STRK-USDT-SWAP",
    "ARKM-USDT-SWAP", "OM-USDT-SWAP", "POLYX-USDT-SWAP", "HOT-USDT-SWAP",
    "DUSK-USDT-SWAP", "HOOK-USDT-SWAP", "PHB-USDT-SWAP", "MAGIC-USDT-SWAP",
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
    # PEPE ve 1000PEPE gibi tüm Pepe tabanlı semboller bloklanır.
    return any(key and key in base for key in BLOCKED_COIN_BASE_KEYWORDS)


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

# -------------------------
# LOGGING
# -------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("balina_avcisi_v5272_para_korumali")

# -------------------------
# GLOBAL STATE
# -------------------------
TZ = ZoneInfo(TIMEZONE_NAME)

# -------------------------
# HTTP SESSION POOL (V5.2.7.2 fix)
# Her thread'e ayrı session — threading.local() ile connection reuse sağlanır.
# Önceki kodda her API çağrısında yeni Session açılıp kapanıyordu (TCP overhead).
# -------------------------
import threading as _threading
_thread_local = _threading.local()

def _get_session() -> requests.Session:
    """Her thread için tek bir requests.Session döndürür (connection pool reuse)."""
    if not hasattr(_thread_local, "session"):
        s = requests.Session()
        s.headers.update({"User-Agent": "BalinaAvcisiV5272ParaKorumali/1.0"})
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=4,
            pool_maxsize=8,
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

memory: Dict[str, Any] = {
    "hot": {},
    "trend_watch": {},
    "signals": {},
    "follows": {},
    "stats": {},
    "daily_short_sent": {},
    "daily_long_sent": {},
    "last_signal_ts": 0.0,
    "last_diag_ts": 0.0,
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
}

app = None
deep_pointer = 0


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
    memory.setdefault("last_signal_ts", 0.0)
    memory.setdefault("last_diag_ts", 0.0)


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
        # JSON serialize edilemez objeleri temizle
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
                # V5.2.7.2: Timezone-aware parse ile 7 günden eski kayıtları temizle
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
    # V5.2.7.2: thread-local session pool
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
    # V5.2.7.2: thread-local session pool kullanılıyor (TCP connection reuse)
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

    # okx_live_symbols boşsa (başlangıç durumu) pas geç, sonraki kontrollere bırak
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


async def get_okx_orderbook(symbol: str, depth: int = 50) -> Dict[str, Any]:
    """
    Public OKX orderbook okuması.
    Amaç: destek duvarı çekiliyor mu, satış duvarı yığılıyor mu, üst/alt likidite nerede bunu izlemek.
    """
    if not GORUNMEYEN_YUZ_ORDERBOOK_ENABLED:
        return {"enabled": False, "ok": False, "reason": "Orderbook motoru kapalı."}

    symbol = normalize_symbol(symbol)
    cache_key = f"BOOK:{symbol}:{depth}"
    cached = orderbook_cache.get(cache_key)
    now_ts = time.time()
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
        if not bids or not asks:
            raise RuntimeError("empty bids/asks")

        best_bid = safe_float(bids[0][0])
        best_ask = safe_float(asks[0][0])
        mid = (best_bid + best_ask) / 2.0 if best_bid > 0 and best_ask > 0 else 0.0
        band = mid * 0.0018 if mid > 0 else 0.0

        bid_near = 0.0
        ask_near = 0.0
        bid_total = 0.0
        ask_total = 0.0

        for row in bids:
            px = safe_float(row[0])
            sz = safe_float(row[1])
            notional = px * sz
            bid_total += notional
            if mid > 0 and px >= mid - band:
                bid_near += notional

        for row in asks:
            px = safe_float(row[0])
            sz = safe_float(row[1])
            notional = px * sz
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
            "ts": now_ts,
            "bid_near": bid_near,
            "ask_near": ask_near,
            "bid_total": bid_total,
            "ask_total": ask_total,
            "book_pressure": book_pressure,
            "full_book_pressure": full_book_pressure,
        }

        result = {
            "enabled": True,
            "ok": True,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid": mid,
            "spread_pct": abs(pct_change(best_bid, best_ask)) if best_bid > 0 and best_ask > 0 else 0.0,
            "bid_near": bid_near,
            "ask_near": ask_near,
            "bid_total": bid_total,
            "ask_total": ask_total,
            "book_pressure": round(book_pressure, 4),
            "full_book_pressure": round(full_book_pressure, 4),
            "bid_wall_pulled": bid_wall_pulled,
            "ask_wall_stacked": ask_wall_stacked,
            "bid_wall_added": bid_wall_added,
            "ask_wall_pulled": ask_wall_pulled,
            "reason": "OKX orderbook okundu.",
        }
        orderbook_cache[cache_key] = (now_ts, result)
        stats["orderbook_ok"] += 1
        return result
    except Exception as e:
        stats["orderbook_fail"] += 1
        logger.warning("OKX orderbook alınamadı %s: %s", symbol, e)
        return {"enabled": True, "ok": False, "reason": f"Orderbook alınamadı: {e}"}


async def get_okx_recent_trades(symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
    """
    Public OKX trade akışı.
    Amaç: agresif alıcı mı basıyor, agresif satıcı mı devralıyor bunu okumak.
    """
    if not GORUNMEYEN_YUZ_TRADES_ENABLED:
        return []

    symbol = normalize_symbol(symbol)
    cache_key = f"TRADES:{symbol}:{limit}"
    cached = trades_cache.get(cache_key)
    now_ts = time.time()
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
            rows.append({
                "px": safe_float(row.get("px", 0)),
                "sz": safe_float(row.get("sz", 0)),
                "side": str(row.get("side", "")).lower(),
                "ts": safe_float(row.get("ts", 0)),
            })
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
    # V5.2.7.2: thread-local session pool
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
    if not values:
        return []
    if len(values) < period:
        base = avg(values)
        return [base for _ in values]
    alpha = 2 / (period + 1)
    out = [avg(values[:period])]
    for v in values[period:]:
        out.append((v * alpha) + (out[-1] * (1 - alpha)))
    pad = [out[0]] * (len(values) - len(out))
    return pad + out


def rsi(values: List[float], period: int = 14) -> List[float]:
    if len(values) < period + 1:
        return [50.0 for _ in values]
    rsis = [50.0] * len(values)
    gains: List[float] = []
    losses: List[float] = []
    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(abs(min(diff, 0.0)))
        if i >= period:
            avg_gain = avg(gains[i - period:i])
            avg_loss = avg(losses[i - period:i])
            rs = 999.0 if avg_loss == 0 else avg_gain / avg_loss
            rsis[i] = 100 - (100 / (1 + rs))
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
    """
    Short için gerçek yapı bozulması ölçümü.
    Sadece pump/RSI yüksek diye SHORT açmayı engeller.
    """
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
    """
    Pump devam ederken erken SHORT'u kilitler.
    Mantık: Coin yükseliyorsa short değil, önce sessiz takip.
    """
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
    """
    Stop: son fitil tepesi + ATR tampon + minimum stop yüzdesi.
    Aşırı uzak stop varsa maksimum stop yüzdesiyle sınırlar.
    """
    if entry <= 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0

    recent_swing_high = max(h1[-12:]) if len(h1) >= 12 else max(h1) if h1 else entry
    min_stop_dist = entry * (SHORT_MIN_STOP_PCT / 100.0)
    atr_stop_dist = max(last_atr1 * SHORT_STOP_ATR_MULT, min_stop_dist)
    wick_buffer = max(last_atr1 * SHORT_STOP_WICK_ATR_BUFFER, entry * 0.0012)
    wick_stop = recent_swing_high + wick_buffer
    raw_stop = max(entry + atr_stop_dist, wick_stop)
    max_stop = entry * (1 + SHORT_MAX_STOP_PCT / 100.0)
    stop = min(raw_stop, max_stop)

    if stop <= entry + min_stop_dist:
        stop = entry + min_stop_dist

    risk = max(stop - entry, min_stop_dist, 1e-9)
    tp1 = entry - (risk * SHORT_TP1_R_MULT)
    tp2 = entry - (risk * SHORT_TP2_R_MULT)
    tp3 = entry - max(risk * SHORT_TP3_R_MULT, last_atr5 * 1.35)
    rr = (entry - tp1) / max(stop - entry, 1e-9)
    return stop, tp1, tp2, tp3, rr




def calculate_long_levels(entry: float, l1: List[float], last_atr1: float, last_atr5: float) -> Tuple[float, float, float, float, float]:
    """
    LONG stop: son dip / likidite süpürme altı + ATR tamponu.
    SHORT stop mantığından tamamen ayrıdır; long tarafında stop entry altındadır.
    """
    if entry <= 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0

    recent_swing_low = min(l1[-12:]) if len(l1) >= 12 else min(l1) if l1 else entry
    min_stop_dist = entry * (LONG_MIN_STOP_PCT / 100.0)
    atr_stop_dist = max(last_atr1 * LONG_STOP_ATR_MULT, min_stop_dist)
    wick_buffer = max(last_atr1 * LONG_STOP_WICK_ATR_BUFFER, entry * 0.0012)
    wick_stop = recent_swing_low - wick_buffer
    raw_stop = min(entry - atr_stop_dist, wick_stop)
    max_stop = entry * (1 - LONG_MAX_STOP_PCT / 100.0)
    stop = max(raw_stop, max_stop)

    if stop >= entry - min_stop_dist:
        stop = entry - min_stop_dist

    risk = max(entry - stop, min_stop_dist, 1e-9)
    tp1 = entry + (risk * LONG_TP1_R_MULT)
    tp2 = entry + (risk * LONG_TP2_R_MULT)
    tp3 = entry + max(risk * LONG_TP3_R_MULT, last_atr5 * 1.25)
    rr = (tp1 - entry) / max(entry - stop, 1e-9)
    return stop, tp1, tp2, tp3, rr



def ict_find_pivots(hs: List[float], ls: List[float], left: int = 2, right: int = 2) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
    """ICT market structure için swing/pivot noktaları."""
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
    """HH/HL/LH/LL, BOS ve CHOCH okuması."""
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
        "hh": hh,
        "hl": hl,
        "lh": lh,
        "ll": ll,
        "last_structure_high": last_high,
        "prev_structure_high": prev_high,
        "last_structure_low": last_low,
        "prev_structure_low": prev_low,
        "bos_up": bos_up,
        "bos_down": bos_down,
        "choch_up": choch_up,
        "choch_down": choch_down,
        "mss_up": mss_up,
        "mss_down": mss_down,
        "pivot_high_count": len(ph),
        "pivot_low_count": len(pl),
    }


def ict_detect_equal_liquidity(k1: List[List[Any]], price: float) -> Dict[str, Any]:
    """Equal high/equal low ve buy-side/sell-side likidite kümeleri."""
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
    """Son 1m mumlarda aktif FVG/imbalance bölgeleri."""
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
    """Basit ama işe yarar OB tespiti: displacement öncesi son karşı renk mum."""
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
            # Bullish displacement; önceki son kırmızı mum demand OB
            for j in range(i-1, max(start-1, i-8), -1):
                oj = safe_float(k1[j][1]); hj = safe_float(k1[j][2]); lj = safe_float(k1[j][3]); cj = safe_float(k1[j][4])
                if cj < oj:
                    bullish_ob = {"low": lj, "high": max(oj, cj), "full_high": hj, "index": j, "age": len(k1)-1-j}
                    break
        if c < o:
            # Bearish displacement; önceki son yeşil mum supply OB
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
    """
    ICT PRO ortak bölge motoru.
    Sinyal üretmez; SHORT ve LONG motorlarına ayrı ayrı profesyonel bağlam verir.
    İçerik: market structure, BOS/CHOCH/MSS, liquidity sweep, equal high/low,
    FVG/imbalance, bullish/bearish order block, premium/discount ve kill zone.
    """
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
        "passed": passed,
        "class": klass,
        "score5": round(score5, 2),
        "score15": round(score15, 2),
        "reason": f"5m long skoru {score5:.1f}/{LONG_MIN_5M_CONFIRM_SCORE:.1f}: {'; '.join(reasons5[:4]) if reasons5 else 'net alıcı yok'} | 15m long skoru {score15:.1f}/{LONG_MIN_15M_CONFIRM_SCORE:.1f}: {'; '.join(reasons15[:4]) if reasons15 else 'ana onay yok'}"
    }

def interval_to_milliseconds(interval: str) -> int:
    mp = {
        "1m": 60_000,
        "3m": 180_000,
        "5m": 300_000,
        "15m": 900_000,
        "30m": 1_800_000,
        "1H": 3_600_000,
        "1h": 3_600_000,
        "4H": 14_400_000,
        "4h": 14_400_000,
    }
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
    """
    1m motoru saniyelik/erken radar olarak çalışır; gerçek SHORT AL kapısı 5m ve 15m
    kapanmış mumlardan geçer. Böylece PENDLE örneğindeki gibi 1 dakikalık yalancı
    zayıflama TEMİZ SHORT diye dışarı basılmaz.
    """
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

    score5 = 0.0
    reasons5: List[str] = []
    if red5:
        score5 += 1.8
        reasons5.append("5m kırmızı kapandı")
    if cl5 < c5v[-2]:
        score5 += 1.1
        reasons5.append("5m önceki kapanış altı")
    if cl5 < e9_5[-1]:
        score5 += 1.4
        reasons5.append("5m EMA9 altı")
    if cl5 < e21_5[-1]:
        score5 += 1.3
        reasons5.append("5m EMA21 altı")
    if upper5 >= 0.22 and cl5 <= o5:
        score5 += 1.0
        reasons5.append("5m üst fitil/red")
    if c5v[-1] < c5v[-2] < c5v[-3]:
        score5 += 1.0
        reasons5.append("5m iki kapanış zayıf")
    if lower5 >= 0.45 and cl5 >= o5:
        score5 -= 1.4
        reasons5.append("5m alt fitil alıcı savunması")
    if cl5 > e9_5[-1] and not red5:
        score5 -= 1.2
        reasons5.append("5m kapanış hâlâ diri")

    score15 = 0.0
    reasons15: List[str] = []
    if red15:
        score15 += 1.4
        reasons15.append("15m kırmızı kapandı")
    if cl15 < c15v[-2]:
        score15 += 1.0
        reasons15.append("15m önceki kapanış altı")
    if cl15 < e9_15[-1]:
        score15 += 1.4
        reasons15.append("15m EMA9 altı")
    if upper15 >= 0.20 and cl15 <= o15:
        score15 += 0.9
        reasons15.append("15m üst fitil/red")
    if r15[-1] >= 62:
        score15 += 0.8
        reasons15.append(f"15m şişkin RSI {r15[-1]:.1f}")
    if lower15 >= 0.45 and cl15 >= o15:
        score15 -= 1.2
        reasons15.append("15m alt fitil alıcı savunması")
    if cl15 > e9_15[-1] and cl15 > c15v[-2] and not red15:
        score15 -= 1.6
        reasons15.append("15m kapanış hâlâ yukarı")

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
    return {
        "passed": passed,
        "class": decision_class,
        "score5": round(score5, 2),
        "score15": round(score15, 2),
        "reason": reason,
    }


def final_quality_gate(res: Dict[str, Any]) -> Tuple[bool, str, float]:
    """
    Para koruma kapısı.
    Yeni mantık: Eğer görünmeyen yüz motoru tepe erken para çıkışı yakaladıysa,
    klasik tam kırılımı bekleyip sinyali öldürmez.
    Ama fiyat çoktan düşmüş / yerel dibe yaklaşmış / recovery başlamışsa yine kilitler.
    """
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
    vol1 = safe_float(res.get("vol_ratio_1m", 0))
    vol5 = safe_float(res.get("vol_ratio_5m", 0))
    pump20 = safe_float(res.get("pump_20m", 0))
    drop_from_peak = safe_float(inv.get("drop_from_peak_pct", 0))
    bounce_from_low = safe_float(inv.get("bounce_from_low_pct", 0))
    top_exit_score = safe_float(inv.get("top_exit_score", 0))

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

    if verify >= MIN_VERIFY_SCORE_FOR_SIGNAL:
        score += 1.4
    elif is_tepe_early and top_exit_score >= TEPE_ERKEN_MIN_EXIT_SCORE:
        score += 0.7
        soft_notes.append(f"doğrulama erken modda düşük kaldı {verify:.1f}")
    else:
        soft_notes.append(f"doğrulama düşük {verify:.1f}/{MIN_VERIFY_SCORE_FOR_SIGNAL:.1f}")

    if red_count >= 1:
        score += 0.8
    elif is_tepe_early:
        score += 0.3
        soft_notes.append("satış mumu az; sadece erken tepe uyarısı")
    else:
        soft_notes.append("satış mumu az")

    if green_streak >= 4 and breakdown < BREAKDOWN_ASSIST_STRONG_SCORE and not is_tepe_early:
        hard_blocks.append(f"yeşil seri devam {green_streak}")
    elif green_streak <= 2 or is_tepe_early:
        score += 0.6

    if trend_guard_score >= 6.0 and breakdown < BREAKDOWN_ASSIST_STRONG_SCORE and not is_tepe_early:
        hard_blocks.append(f"trend kilidi yüksek {trend_guard_score:.1f}")
    elif trend_guard_score <= 5.2 or is_tepe_early:
        score += 0.7

    if pump20 >= 3.2 and rsi1_val >= 66 and rsi5_val >= 64 and breakdown < BREAKDOWN_ASSIST_STRONG_SCORE and not is_tepe_early:
        hard_blocks.append(f"yüksek hacimli pump devam ediyor %{pump20:.2f}")

    if rsi1_val <= 62 or breakdown >= BREAKDOWN_ASSIST_STRONG_SCORE or is_tepe_early:
        score += 0.5
    else:
        soft_notes.append(f"RSI1 hâlâ diri {rsi1_val:.1f}")

    if vol1 >= 0.75 or vol5 >= 0.65 or is_tepe_early:
        score += 0.5
    else:
        soft_notes.append(f"hacim zayıf x{vol1:.2f}")

    passed = score >= MIN_QUALITY_SCORE and not hard_blocks
    reason_parts = hard_blocks if hard_blocks else soft_notes
    return passed, " | ".join(reason_parts[:6]) if reason_parts else "Para koruma kapısı temiz", round(score, 2)


def candle_wick_ratios(kline: List[Any]) -> Tuple[float, float, float, bool]:
    o = safe_float(kline[1])
    h = safe_float(kline[2])
    l = safe_float(kline[3])
    c = safe_float(kline[4])
    rng = max(h - l, 1e-9)  # V5.2.7.2: daha güvenli sıfır koruması
    upper = max(0.0, h - max(o, c)) / rng
    lower = max(0.0, min(o, c) - l) / rng
    body = abs(c - o) / rng
    red = c < o
    return upper, lower, body, red


def fmt_bool(v: bool) -> str:
    return "VAR" if bool(v) else "YOK"


def empty_invisible_face(reason: str = "Görünmeyen yüz motoru kapalı.") -> Dict[str, Any]:
    return {
        "enabled": False,
        "score": 0.0,
        "class": "KAPALI",
        "decision": "ESKİ_KAPI",
        "short_allowed": True,
        "risk_scalp_allowed": False,
        "watch_only": False,
        "hard_block": False,
        "av_nerede": "-",
        "likidite_nerede": "-",
        "kucuk_yatirimci_nerede": "-",
        "tuzak": "-",
        "tepe_stop_hunt": "-",
        "buyuk_para_izi": "-",
        "dagitim_nerede": "-",
        "supurme_hedefi": "-",
        "islem_alinabilir_mi": "-",
        "tp1_gercekci_mi": "-",
        "stop_mantikli_mi": "-",
        "ema_rsi_durumu": "-",
        "orderbook_izi": "-",
        "trade_flow_izi": "-",
        "top_early_short": False,
        "top_exit_score": 0.0,
        "top_exit_reason": "-",
        "peak_age_candles": 0,
        "reasons": [reason],
    }


async def build_invisible_face_short(
    *,
    symbol: str,
    payload: Dict[str, Any],
    k1: List[List[Any]],
    k5: List[List[Any]],
    k15: List[List[Any]],
    failed_breakout: bool,
    micro_bear: bool,
    bear_cross: bool,
    losing_momentum: bool,
    weak_close: bool,
    structure_turn: bool,
    rej_score: float,
    breakdown_reason: str,
) -> Dict[str, Any]:
    """
    GÖRÜNMEYEN YÜZ MOTORU
    Bu motor klasik EMA/RSI karar motoru değildir.
    Public veriden şunları okur:
    - Av nerede?
    - Likidite nerede?
    - Küçük yatırımcı nereye çekildi?
    - Alıcı/satıcı tuzağı var mı?
    - Stop hunt / tepe süpürme var mı?
    - Orderbook duvarı çekiliyor veya satış duvarı yığılıyor mu?
    - Agresif trade flow satışa mı döndü?
    - Fiyat hâlâ alınabilir yerde mi, yoksa geç kalındı mı?
    """
    if not GORUNMEYEN_YUZ_ENABLED:
        return empty_invisible_face()

    score = 0.0
    reasons: List[str] = []
    hard_blocks: List[str] = []
    warning_notes: List[str] = []

    c1 = closes(k1)
    h1 = highs(k1)
    l1 = lows(k1)
    v1 = volumes(k1)
    c5 = closes(k5)
    h5 = highs(k5)
    l5 = lows(k5)

    if len(c1) < 40 or len(c5) < 30:
        blocked = empty_invisible_face("Görünmeyen yüz için veri yetersiz.")
        blocked["enabled"] = True
        blocked["short_allowed"] = False
        blocked["hard_block"] = True
        blocked["decision"] = "VERİ_YETERSİZ"
        return blocked

    price = safe_float(payload.get("price", c1[-1]))
    entry = price
    stop = safe_float(payload.get("stop", 0))
    tp1 = safe_float(payload.get("tp1", 0))
    rr = safe_float(payload.get("rr", 0))
    pump_10m = safe_float(payload.get("pump_10m", 0))
    pump_20m = safe_float(payload.get("pump_20m", 0))
    pump_1h = safe_float(payload.get("pump_1h", 0))
    rsi1_val = safe_float(payload.get("rsi1", 50))
    rsi5_val = safe_float(payload.get("rsi5", 50))
    rsi15_val = safe_float(payload.get("rsi15", 50))
    vol_ratio_1m = safe_float(payload.get("vol_ratio_1m", 0))
    vol_ratio_5m = safe_float(payload.get("vol_ratio_5m", 0))
    breakdown_score = safe_float(payload.get("breakdown_score", 0))
    trend_guard_score = safe_float(payload.get("trend_guard_score", 0))
    candidate_score = safe_float(payload.get("candidate_score", 0))
    ready_score = safe_float(payload.get("ready_score", 0))
    verify_score = safe_float(payload.get("verify_score", 0))

    last_k = k1[-1]
    prev_k = k1[-2]
    last_open = safe_float(last_k[1])
    last_high = safe_float(last_k[2])
    last_low = safe_float(last_k[3])
    last_close = safe_float(last_k[4])
    prev_high_lookback = max(h1[-45:-2]) if len(h1) >= 45 else max(h1[:-2])
    prev_low_lookback = min(l1[-45:-2]) if len(l1) >= 45 else min(l1[:-2])
    peak_45 = max(h1[-45:])
    peak_window_45 = h1[-45:]
    peak_age_candles = 0
    for idx in range(len(peak_window_45) - 1, -1, -1):
        if peak_window_45[idx] == peak_45:
            peak_age_candles = len(peak_window_45) - 1 - idx
            break
    peak_90 = max(h1[-90:]) if len(h1) >= 90 else max(h1)
    local_low_30 = min(l1[-30:])
    local_high_20 = max(h1[-21:-1])
    upper_wick, lower_wick, body_ratio, is_red = candle_wick_ratios(last_k)

    drop_from_peak = ((peak_45 - price) / peak_45 * 100.0) if peak_45 > 0 else 0.0
    drop_from_peak_90 = ((peak_90 - price) / peak_90 * 100.0) if peak_90 > 0 else 0.0
    bounce_from_low = pct_change(local_low_30, price) if local_low_30 > 0 else 0.0
    tp1_distance_pct = abs(pct_change(entry, tp1)) if entry > 0 and tp1 > 0 else 0.0
    stop_distance_pct = abs(pct_change(entry, stop)) if entry > 0 and stop > 0 else 0.0

    # -------------------------------------------------
    # Live orderbook/trade flow: her zayıf coinde API'yi boğmamak için prefilter.
    # -------------------------------------------------
    flow_prefilter = (
        safe_float(payload.get("score", 0)) >= GORUNMEYEN_YUZ_FLOW_PREFILTER_SCORE
        or pump_20m >= 0.70
        or failed_breakout
        or rej_score >= 8
        or candidate_score + ready_score + verify_score >= GORUNMEYEN_YUZ_FLOW_PREFILTER_SCORE
    )

    book = {"ok": False, "reason": "Prefilter geçmedi; kline ile okundu."}
    flow = {
        "buy_notional": 0.0, "sell_notional": 0.0, "buy_count": 0, "sell_count": 0,
        "sell_ratio": 0.0, "buy_ratio": 0.0, "sell_to_buy": 0.0, "buy_to_sell": 0.0,
    }

    if flow_prefilter:
        book = await get_okx_orderbook(symbol, 50)
        trades = await get_okx_recent_trades(symbol, 100)
        flow = analyze_trade_flow(trades)

    # -------------------------------------------------
    # 1) AV NEREDE?
    # -------------------------------------------------
    near_peak = GORUNMEYEN_YUZ_MIN_DROP_FROM_PEAK <= drop_from_peak <= GORUNMEYEN_YUZ_MAX_DROP_FROM_PEAK
    early_top_zone = TEPE_ERKEN_MIN_DROP_FROM_PEAK <= drop_from_peak <= TEPE_ERKEN_MAX_DROP_FROM_PEAK
    not_yet_confirmed = drop_from_peak < GORUNMEYEN_YUZ_MIN_DROP_FROM_PEAK
    too_late = drop_from_peak > min(GORUNMEYEN_YUZ_TOO_LATE_DROP, TEPE_ERKEN_TOO_LATE_DROP)
    no_real_pump = pump_20m < 0.55 and pump_1h < 1.05

    if near_peak:
        av_nerede = f"Tepe av alanı: zirve {fmt_num(peak_45)}, fiyat zirveden %{drop_from_peak:.2f} aşağıda"
        score += 15
    elif not_yet_confirmed:
        av_nerede = f"Tepe çok yakın ama kırılım daha ham: zirveden %{drop_from_peak:.2f}"
        score += 4
        warning_notes.append("Tepeden düşüş çok az; erken uyarı olabilir ama AL için net değil.")
    elif too_late:
        av_nerede = f"Av kaçmış olabilir: zirveden %{drop_from_peak:.2f} aşağıda"
        score -= 24
        hard_blocks.append("Fiyat tepeden fazla uzaklaştı; geç short/düşüş kovalamaya dönebilir.")
    else:
        av_nerede = f"Av alanı sınırda: zirveden %{drop_from_peak:.2f}"
        score += 3

    if no_real_pump:
        score -= 10
        warning_notes.append("Pump bağlamı zayıf; sıradan geri çekilme olabilir.")
    elif pump_20m >= 1.0 or pump_1h >= 1.6:
        score += 9
        reasons.append("Pump bağlamı var; av alanı anlamlı.")

    # -------------------------------------------------
    # 2) LİKİDİTE NEREDE / STOP HUNT
    # -------------------------------------------------
    swept_upper = last_high > prev_high_lookback and last_close < prev_high_lookback
    swept_lower = last_low < prev_low_lookback and last_close > prev_low_lookback
    close_failed_near_top = last_high >= peak_45 * 0.998 and last_close < last_high * 0.9975
    wick_rejection = upper_wick >= 0.16 and is_red

    if swept_upper:
        likidite_nerede = "Üst likidite süpürüldü; long stop/tepe avı alınmış olabilir"
        tepe_stop_hunt = "VAR: eski tepe üstüne iğne + geri kapanış"
        score += 23
    elif failed_breakout:
        likidite_nerede = "Üst likidite yoklandı; sahte kırılım izi var"
        tepe_stop_hunt = "VAR: fake breakout"
        score += 17
    elif close_failed_near_top or wick_rejection:
        likidite_nerede = "Tepe bölgesinde likidite yoklandı; red izi var"
        tepe_stop_hunt = "KISMİ: tepe/red var"
        score += 12
    elif swept_lower:
        likidite_nerede = "Alt likidite alınmış; short için satıcı tuzağı riski"
        tepe_stop_hunt = "YOK: aşağı süpürme var"
        score -= 18
        hard_blocks.append("Alt likidite süpürülmüş; tepki long riski var.")
    else:
        likidite_nerede = "Likidite yönü net değil; üst av teyidi zayıf"
        tepe_stop_hunt = "NET DEĞİL"
        score -= 4

    # -------------------------------------------------
    # 3) KÜÇÜK YATIRIMCI NEREYE ÇEKİLDİ / TUZAK
    # -------------------------------------------------
    buyer_trap = (swept_upper or failed_breakout or wick_rejection or close_failed_near_top) and (near_peak or early_top_zone)
    seller_trap = swept_lower or (lower_wick >= 0.24 and bounce_from_low >= 0.45 and breakdown_score < TREND_BREAKDOWN_MIN_SCORE)

    if buyer_trap:
        tuzak = "ALICI TUZAĞI: fiyat tepeye çekilip yukarı devam ettirilememiş"
        kucuk_yatirimci = "Long tarafı tepeye çekilmiş olabilir"
        score += 20
    elif seller_trap:
        tuzak = "SATICI TUZAĞI RİSKİ: dipten iğne/toparlanma var"
        kucuk_yatirimci = "Shortçular aşağıda tuzağa çekiliyor olabilir"
        score -= 24
        hard_blocks.append("Satıcı tuzağı riski; short açma.")
    else:
        tuzak = "Tuzak net değil"
        kucuk_yatirimci = "Net sürü psikolojisi yönü okunmadı"
        score -= 5

    # -------------------------------------------------
    # 4) BÜYÜK PARA / DAĞITIM İZİ
    # -------------------------------------------------
    distribution_points = 0
    distribution_notes: List[str] = []

    if losing_momentum or rsi1_val < 55:
        distribution_points += 1
        distribution_notes.append("alıcı ivmesi zayıflıyor")
        score += 5
    if micro_bear or weak_close:
        distribution_points += 1
        distribution_notes.append("zayıf kapanış / mikro satış")
        score += 7
    if bear_cross:
        distribution_points += 1
        distribution_notes.append("kısa EMA devri aşağı")
        score += 4
    if breakdown_score >= TREND_BREAKDOWN_MIN_SCORE:
        distribution_points += 2
        distribution_notes.append(f"kırılım skoru {breakdown_score:.1f}")
        score += 12
    elif breakdown_score >= TREND_BREAKDOWN_MIN_SCORE * 0.65:
        distribution_points += 1
        distribution_notes.append(f"yarım kırılım {breakdown_score:.1f}")
        score += 5
    if vol_ratio_1m >= 0.45 or vol_ratio_5m >= 0.35:
        distribution_points += 1
        distribution_notes.append("hacim tamamen ölü değil")
        score += 4
    else:
        warning_notes.append("Hacim çok sönük; bu hareket sadece alıcı yokluğu olabilir.")

    # Orderbook izi
    book_pressure = safe_float(book.get("book_pressure", 0))
    bid_wall_pulled = bool(book.get("bid_wall_pulled", False))
    ask_wall_stacked = bool(book.get("ask_wall_stacked", False))
    bid_wall_added = bool(book.get("bid_wall_added", False))
    ask_wall_pulled = bool(book.get("ask_wall_pulled", False))

    orderbook_parts: List[str] = []
    if book.get("ok"):
        if bid_wall_pulled:
            distribution_points += 1
            score += 11
            orderbook_parts.append("destek duvarı çekildi")
        if ask_wall_stacked:
            distribution_points += 1
            score += 9
            orderbook_parts.append("üst satış duvarı yığılıyor")
        if book_pressure >= 0.18:
            distribution_points += 1
            score += 7
            orderbook_parts.append(f"ask baskısı %{book_pressure * 100:.1f}")
        if bid_wall_added or ask_wall_pulled:
            score -= 7
            orderbook_parts.append("alıcı savunması/ask çekilmesi var")
            warning_notes.append("Orderbook kısa vadeli tepkiyi destekleyebilir.")
        if not orderbook_parts:
            orderbook_parts.append(f"nötr/karışık book basıncı %{book_pressure * 100:.1f}")
    else:
        orderbook_parts.append(str(book.get("reason", "Orderbook yok")))

    # Trade flow izi
    sell_to_buy = safe_float(flow.get("sell_to_buy", 0))
    buy_to_sell = safe_float(flow.get("buy_to_sell", 0))
    sell_ratio = safe_float(flow.get("sell_ratio", 0))
    trade_parts: List[str] = []

    if flow.get("buy_notional", 0) or flow.get("sell_notional", 0):
        if sell_to_buy >= 1.25:
            distribution_points += 1
            score += 10
            trade_parts.append(f"agresif satış baskın x{sell_to_buy:.2f}")
        elif buy_to_sell >= 1.35:
            score -= 10
            trade_parts.append(f"agresif alıcı hâlâ güçlü x{buy_to_sell:.2f}")
            warning_notes.append("Trade flow alıcıyı gösteriyor; short erken olabilir.")
        else:
            trade_parts.append(f"trade flow dengeli; satış oranı %{sell_ratio * 100:.1f}")
    else:
        trade_parts.append("trade flow yok/okunamadı")

    # -------------------------------------------------
    # 4.5) TEPE ERKEN PARA ÇIKIŞI
    # -------------------------------------------------
    top_exit_score = 0.0
    top_exit_reasons: List[str] = []
    strong_pump_context = pump_20m >= TEPE_ERKEN_MIN_PUMP_20M or pump_1h >= TEPE_ERKEN_MIN_PUMP_1H
    fresh_peak = peak_age_candles <= TEPE_ERKEN_MAX_PEAK_AGE_CANDLES
    early_not_local_low = not (drop_from_peak > 1.0 and bounce_from_low <= TEPE_ERKEN_BLOCK_LOCAL_LOW_BOUNCE)

    if strong_pump_context:
        top_exit_score += 1.0
        top_exit_reasons.append("pump var")
    if early_top_zone:
        top_exit_score += 1.0
        top_exit_reasons.append(f"tepeye yakın %{drop_from_peak:.2f}")
    if fresh_peak:
        top_exit_score += 0.7
        top_exit_reasons.append(f"tepe taze {peak_age_candles} mum")
    if swept_upper or failed_breakout or close_failed_near_top or wick_rejection:
        top_exit_score += 1.2
        top_exit_reasons.append("tepe red/likidite yoklama")
    if losing_momentum or weak_close or micro_bear:
        top_exit_score += 0.8
        top_exit_reasons.append("alıcı zayıflama başladı")
    if book.get("ok") and (bid_wall_pulled or ask_wall_stacked or book_pressure >= 0.12):
        top_exit_score += 1.0
        top_exit_reasons.append("orderbook para çıkışı")
    effective_sell_takeover_min = min(TEPE_ERKEN_STRONG_SELL_TO_BUY, FIRST_BREAK_SELL_TAKEOVER_MIN) if FIRST_BREAK_ENGINE_ENABLED else TEPE_ERKEN_STRONG_SELL_TO_BUY
    if sell_to_buy >= effective_sell_takeover_min:
        top_exit_score += 1.0
        top_exit_reasons.append(f"satış akışı x{sell_to_buy:.2f}")
    if FIRST_BREAK_ENGINE_ENABLED and breakdown_score >= FIRST_BREAK_MIN_BREAKDOWN_SCORE:
        top_exit_score += 0.7
        top_exit_reasons.append(f"ilk kırılım desteği {breakdown_score:.1f}")
    if buy_to_sell >= TEPE_ERKEN_STRONG_BUY_TO_SELL_BLOCK and sell_to_buy < 1.0:
        top_exit_score -= 1.4
        top_exit_reasons.append(f"alıcı hâlâ baskın x{buy_to_sell:.2f}")
    if too_late or not early_not_local_low:
        top_exit_score -= 3.0
        top_exit_reasons.append("geç kalmış/dip bölgesi")

    effective_top_exit_min = min(TEPE_ERKEN_MIN_EXIT_SCORE, FIRST_BREAK_MIN_SCORE) if FIRST_BREAK_ENGINE_ENABLED else TEPE_ERKEN_MIN_EXIT_SCORE
    first_break_flow_ok = (
        sell_to_buy >= effective_sell_takeover_min
        or breakdown_score >= FIRST_BREAK_MIN_BREAKDOWN_SCORE
        or failed_breakout
        or weak_close
        or micro_bear
        or wick_rejection
    )
    top_early_short = bool(
        TEPE_ERKEN_MOD_ENABLED
        and top_exit_score >= effective_top_exit_min
        and strong_pump_context
        and early_top_zone
        and fresh_peak
        and early_not_local_low
        and first_break_flow_ok
        and not seller_trap
        and not too_late
    )

    if top_early_short:
        distribution_points += 1
        score += 15
        reasons.append("Tepe erken para çıkışı modu: " + " | ".join(top_exit_reasons[:5]))
    elif drop_from_peak > TEPE_ERKEN_TOO_LATE_DROP or not early_not_local_low:
        warning_notes.append("Düşüş bitmiş/kaçmış bölge; tepe erken modu sinyal vermez.")

    if distribution_points >= 5:
        buyuk_para_izi = "GÜÇLÜ: dağıtım/çıkış izi birden fazla katmanda var"
        dagitim_nerede = "Tepe bölgesi + mikro kırılım + orderflow"
    elif distribution_points >= 3:
        buyuk_para_izi = "ORTA: dağıtım başlangıcı var ama kusursuz değil"
        dagitim_nerede = "Tepe sonrası ilk çözülme alanı"
    elif distribution_points >= 2 and buyer_trap:
        buyuk_para_izi = "ERKEN: alıcı tuzağı var, dağıtım henüz sertleşmemiş"
        dagitim_nerede = "Tepeye yakın erken dağıtım denemesi"
    else:
        buyuk_para_izi = "ZAYIF: büyük para çıkış izi net değil"
        dagitim_nerede = "Dağıtım alanı okunmadı"
        score -= 11
        warning_notes.append("Dağıtım izi zayıf.")

    orderbook_izi = " | ".join(orderbook_parts[:4])
    trade_flow_izi = " | ".join(trade_parts[:3])

    # -------------------------------------------------
    # 5) FİYAT NEREYE KADAR SÜPÜRÜLÜR / TP1
    # -------------------------------------------------
    if 0.25 <= tp1_distance_pct <= 1.40 and rr >= GORUNMEYEN_YUZ_MIN_RR_TP1:
        supurme_hedefi = f"İlk süpürme TP1 bölgesi: {fmt_num(tp1)}"
        tp1_gercekci_mi = f"EVET: TP1 mesafe %{tp1_distance_pct:.2f}, RR {rr:.2f}"
        score += 12
    elif tp1_distance_pct < 0.25:
        supurme_hedefi = "Süpürme alanı dar; komisyon/slippage sonrası verimsiz olabilir"
        tp1_gercekci_mi = f"ZAYIF: TP1 çok yakın %{tp1_distance_pct:.2f}"
        score -= 7
    else:
        supurme_hedefi = "TP1 için ekstra satış gerekir; ilk süpürme kolay değil"
        tp1_gercekci_mi = f"ORTA/ZOR: TP1 mesafe %{tp1_distance_pct:.2f}, RR {rr:.2f}"
        score -= 5

    # -------------------------------------------------
    # 6) İŞLEM HÂLÂ ALINABİLİR Mİ?
    # -------------------------------------------------
    near_local_low = bounce_from_low < 0.25 and drop_from_peak > 1.0
    recovery_risk = bounce_from_low >= 0.70 and lower_wick >= 0.20 and breakdown_score < BREAKDOWN_ASSIST_STRONG_SCORE

    if too_late or near_local_low:
        islem_alinabilir_mi = "HAYIR: fiyat düşüş sonrası yerel dibe/kaçmış bölgeye yakın"
        hard_blocks.append("Yerel dip/geç kalmış düşüş riski.")
        score -= 18
    elif recovery_risk:
        islem_alinabilir_mi = "HAYIR/BEKLE: recovery-tepki riski var"
        hard_blocks.append("Recovery riski var; short kovalamaya girer.")
        score -= 15
    elif top_early_short and distribution_points >= 3:
        islem_alinabilir_mi = "EVET/ERKEN: düşüş bitmeden tepe para çıkışı başladı"
        score += 13
    elif buyer_trap and distribution_points >= 4 and (near_peak or early_top_zone):
        islem_alinabilir_mi = "EVET: tepe avı + dağıtım izi + alınabilir mesafe"
        score += 14
    elif buyer_trap and (near_peak or early_top_zone):
        islem_alinabilir_mi = "RİSKLİ SCALP: alıcı tuzağı var ama dağıtım tam sert değil"
        score += 6
    else:
        islem_alinabilir_mi = "TAKİP: av var/yok net değil, AL için erken"

    # -------------------------------------------------
    # 7) STOP MANTIKLI MI?
    # -------------------------------------------------
    stop_above_peak = stop > peak_45
    stop_above_last_high = stop > last_high
    stop_too_close = stop_distance_pct < SHORT_MIN_STOP_PCT * 0.85
    stop_too_wide = stop_distance_pct > SHORT_MAX_STOP_PCT

    if (stop_above_peak or stop_above_last_high) and not stop_too_close and not stop_too_wide:
        stop_mantikli_mi = f"EVET: stop tepe/süpürme üstünde, mesafe %{stop_distance_pct:.2f}"
        score += 8
    elif stop_too_wide:
        stop_mantikli_mi = f"ZAYIF: stop çok uzak %{stop_distance_pct:.2f}; RR bozulabilir"
        score -= 8
        warning_notes.append("Stop çok geniş; işlem boyutu küçülmeli veya pas geçilmeli.")
    else:
        stop_mantikli_mi = f"HAYIR: stop tepe/süpürme üstünde değil veya çok yakın %{stop_distance_pct:.2f}"
        score -= 12
        hard_blocks.append("Stop mantığı zayıf; son tepe üstünü korumuyor.")

    # -------------------------------------------------
    # 8) EMA/RSI DESTEK Mİ, TUZAK MI?
    # -------------------------------------------------
    price_below_ema_signal = "EMA altı" in str(payload.get("reason", "")) or verify_score >= MIN_VERIFY_SCORE_FOR_SIGNAL
    if trend_guard_score >= TREND_GUARD_SCORE_BLOCK and breakdown_score < TREND_BREAKDOWN_MIN_SCORE:
        ema_rsi_durumu = "KANDIRIYOR: RSI/EMA hareketi trend devamını gizliyor olabilir"
        score -= 10
        warning_notes.append("Trend kilidi yüksekken EMA/RSI ile short açma.")
    elif rsi15_val >= 70 and buyer_trap:
        ema_rsi_durumu = "DESTEK: 15dk şişkinlik alıcı tuzağını destekliyor ama ana sebep değil"
        score += 4
    elif price_below_ema_signal and buyer_trap:
        ema_rsi_durumu = "DESTEK: EMA/RSI sadece tuzak okumasını teyit ediyor"
        score += 3
    else:
        ema_rsi_durumu = "NÖTR: EMA/RSI tek başına karar sebebi değil"

    # -------------------------------------------------
    # Son karar
    # -------------------------------------------------
    score = clamp(score, 0.0, 100.0)

    # Çok zayıf satış devralmada bile WIF gibi erken avlar tamamen öldürülmesin;
    # fakat temiz short sayılmasın, riskli scalp/takip olarak ayrı sınıflansın.
    clean_short = (
        score >= GORUNMEYEN_YUZ_MIN_CLEAN_SCORE
        and buyer_trap
        and distribution_points >= 4
        and not hard_blocks
        and rr >= GORUNMEYEN_YUZ_MIN_RR_TP1
        and (near_peak or early_top_zone)
    )

    risky_scalp = (
        score >= GORUNMEYEN_YUZ_MIN_SCALP_SCORE
        and buyer_trap
        and not too_late
        and not seller_trap
        and rr >= GORUNMEYEN_YUZ_MIN_RR_TP1
        and drop_from_peak <= GORUNMEYEN_YUZ_MAX_DROP_FROM_PEAK
    )

    if top_early_short and not hard_blocks:
        decision_class = "TEPE ERKEN SHORT"
        decision = "TEPE_PARA_CIKISI_SERBEST"
        short_allowed = True
        risk_scalp_allowed = True
        stats["tepe_early_signal"] += 1
    elif clean_short:
        decision_class = "TEMİZ SHORT AL"
        decision = "SHORT_AL_SERBEST"
        short_allowed = True
        risk_scalp_allowed = False
    elif risky_scalp and GORUNMEYEN_YUZ_ALLOW_RISKY_SCALP:
        decision_class = "RİSKLİ TP1 SCALP"
        decision = "TP1_SCALP_SERBEST"
        short_allowed = True
        risk_scalp_allowed = True
    elif hard_blocks:
        decision_class = "BLOK"
        decision = "AL_YOK"
        short_allowed = False
        risk_scalp_allowed = False
    elif score >= GORUNMEYEN_YUZ_MIN_WATCH_SCORE:
        decision_class = "SHORT AV TAKİP"
        decision = "TAKİP"
        short_allowed = False
        risk_scalp_allowed = False
    else:
        decision_class = "AV YOK"
        decision = "SUS"
        short_allowed = False
        risk_scalp_allowed = False

    all_reasons = reasons + distribution_notes + warning_notes + hard_blocks
    if not all_reasons:
        all_reasons = ["Görünmeyen yüz okuması nötr."]

    return {
        "enabled": True,
        "score": round(score, 1),
        "class": decision_class,
        "decision": decision,
        "short_allowed": short_allowed,
        "risk_scalp_allowed": risk_scalp_allowed,
        "watch_only": not short_allowed and score >= GORUNMEYEN_YUZ_MIN_WATCH_SCORE,
        "hard_block": bool(hard_blocks),
        "av_nerede": av_nerede,
        "likidite_nerede": likidite_nerede,
        "kucuk_yatirimci_nerede": kucuk_yatirimci,
        "tuzak": tuzak,
        "tepe_stop_hunt": tepe_stop_hunt,
        "buyuk_para_izi": buyuk_para_izi,
        "dagitim_nerede": dagitim_nerede,
        "supurme_hedefi": supurme_hedefi,
        "islem_alinabilir_mi": islem_alinabilir_mi,
        "tp1_gercekci_mi": tp1_gercekci_mi,
        "stop_mantikli_mi": stop_mantikli_mi,
        "ema_rsi_durumu": ema_rsi_durumu,
        "orderbook_izi": orderbook_izi,
        "trade_flow_izi": trade_flow_izi,
        "top_early_short": top_early_short,
        "top_exit_score": round(top_exit_score, 2),
        "top_exit_reason": " | ".join(top_exit_reasons[:7]) if top_exit_reasons else "-",
        "peak_age_candles": peak_age_candles,
        "peak_price": peak_45,
        "drop_from_peak_pct": round(drop_from_peak, 2),
        "drop_from_peak_90_pct": round(drop_from_peak_90, 2),
        "bounce_from_low_pct": round(bounce_from_low, 2),
        "upper_wick_ratio": round(upper_wick, 3),
        "lower_wick_ratio": round(lower_wick, 3),
        "distribution_points": distribution_points,
        "breakdown_reason": breakdown_reason,
        "reasons": all_reasons[:10],
    }



def apply_risky_scalp_close_targets(res: Dict[str, Any]) -> Dict[str, Any]:
    """
    RİSKLİ TP1 SCALP için uzak TP mantığını değiştirir.
    Bu sınıfın amacı temiz trend shortu değil, tepe sonrası hızlı al-kaçtır.
    Bu yüzden TP1/TP2/TP3 yüzdesel ve yakındır; normal SHORT AL hedefleri korunur.
    """
    if not RISKY_SCALP_CLOSE_TP_ENABLED:
        return res

    # Deep copy yaparak orijinal dict'i koru
    res = copy.deepcopy(res)

    entry = safe_float(res.get("price", 0))
    stop = safe_float(res.get("stop", 0))
    if entry <= 0 or stop <= entry:
        return res

    tp1_pct = max(0.05, RISKY_SCALP_TP1_PCT)
    tp2_pct = max(tp1_pct + 0.05, RISKY_SCALP_TP2_PCT)
    tp3_pct = max(tp2_pct + 0.05, RISKY_SCALP_TP3_PCT)

    old_tp1 = safe_float(res.get("tp1", 0))
    old_tp2 = safe_float(res.get("tp2", 0))
    old_tp3 = safe_float(res.get("tp3", 0))

    new_tp1 = entry * (1 - tp1_pct / 100.0)
    new_tp2 = entry * (1 - tp2_pct / 100.0)
    new_tp3 = entry * (1 - tp3_pct / 100.0)

    new_tp1 = min(new_tp1, entry * 0.999)
    new_tp2 = min(new_tp2, new_tp1 * 0.999)
    new_tp3 = min(new_tp3, new_tp2 * 0.999)

    rr = (entry - new_tp1) / max(stop - entry, 1e-9)

    res["tp1"] = new_tp1
    res["tp2"] = new_tp2
    res["tp3"] = new_tp3
    res["rr"] = round(rr, 2)
    res["risky_scalp_close_tp"] = True
    res["risky_scalp_tp_note"] = (
        f"Riskli scalp yakın TP modu: TP1 %{tp1_pct:.2f}, TP2 %{tp2_pct:.2f}, TP3 %{tp3_pct:.2f}. "
        f"Eski TP1/TP2/TP3: {fmt_num(old_tp1)} / {fmt_num(old_tp2)} / {fmt_num(old_tp3)}"
    )

    res["reason"] = (
        f"{res.get('reason', '')} | Riskli scalp yakın hedef: "
        f"TP1 %{tp1_pct:.2f}, TP2 %{tp2_pct:.2f}, TP3 %{tp3_pct:.2f}"
    )[:1200]

    inv = res.get("invisible_face")
    if isinstance(inv, dict):
        inv["supurme_hedefi"] = f"Riskli scalp ilk süpürme TP1 yakın hedef: {fmt_num(new_tp1)}"
        inv["tp1_gercekci_mi"] = f"SCALP TP: TP1 yakın %{tp1_pct:.2f}; temiz short hedefi değil, al-kaç hedefi"
        inv["reasons"] = [
            f"Riskli scalp olduğu için TP1 uzak tutulmadı; yakın hedef %{tp1_pct:.2f}.",
            *list(inv.get("reasons", []))
        ][:10]
    return res

def _invisible_face_can_promote_to_signal(res: Dict[str, Any], inv: Dict[str, Any], stage: str) -> Tuple[bool, str]:
    """
    FIRSAT KAÇIRMA FIX:
    Görünmeyen yüz/tepe erken motoru gerçekten temiz tepe para çıkışı yakaladıysa
    HOT/READY iç takipte boğulmasın; SHORT AL kapısına yükseltebilsin.
    Riskli scalp veya sadece WATCH burada yükseltilmez.
    """
    if not INVISIBLE_FACE_PROMOTE_SIGNAL_ENABLED:
        return False, "promote kapalı"
    if stage == "SIGNAL":
        return False, "zaten signal"
    if not inv.get("short_allowed") or inv.get("hard_block"):
        return False, "short allowed değil veya hard block var"

    inv_class = str(inv.get("class", ""))
    inv_score = safe_float(inv.get("score", 0))
    top_exit_score = safe_float(inv.get("top_exit_score", 0))
    breakdown = safe_float(res.get("breakdown_score", 0))
    rr = safe_float(res.get("rr", 0))
    drop_from_peak = safe_float(inv.get("drop_from_peak_pct", 999))
    top_early = bool(inv.get("top_early_short", False))

    if drop_from_peak >= TEPE_ERKEN_TOO_LATE_DROP:
        return False, f"geç kalmış %{drop_from_peak:.2f}"
    if rr < RISKY_SCALP_MIN_RR_TP1:
        return False, f"RR zayıf {rr:.2f}"

    if inv_class == "TEMİZ SHORT AL" and inv_score >= GORUNMEYEN_YUZ_MIN_CLEAN_SCORE:
        return True, f"görünmeyen yüz temiz {inv_score:.1f}"

    if (
        TEPE_ERKEN_PROMOTE_SIGNAL_ENABLED
        and top_early
        and inv_class == "TEPE ERKEN SHORT"
        and inv_score >= TEPE_ERKEN_PROMOTE_MIN_INVISIBLE_SCORE
        and top_exit_score >= TEPE_ERKEN_MIN_EXIT_SCORE
        and breakdown >= TEPE_ERKEN_PROMOTE_MIN_BREAKDOWN_SCORE
    ):
        return True, f"tepe erken para çıkışı {inv_score:.1f}, kırılım {breakdown:.1f}"

    return False, f"sınıf yükseltmeye uygun değil {inv_class}/{inv_score:.1f}"


def apply_invisible_face_gate(res: Dict[str, Any]) -> Dict[str, Any]:
    """
    FIRSAT KAÇIRMA FIX:
    - WATCH/SCALP otomatik AL değildir.
    - Ama TEMİZ SHORT AL veya TEPE ERKEN SHORT gerçekten netse HOT/READY içinde boğulmaz,
      dışarı gidebilecek tek etiket olan SHORT AL'a yükselir.
    """
    res = copy.deepcopy(res)
    inv = res.get("invisible_face")
    if not inv or not inv.get("enabled"):
        return res

    res["invisible_score"] = inv.get("score", 0)
    res["invisible_class"] = inv.get("class", "-")
    res["invisible_decision"] = inv.get("decision", "-")
    res["top_early_short"] = bool(inv.get("top_early_short", False))
    res["top_exit_score"] = inv.get("top_exit_score", 0)
    res["top_exit_reason"] = inv.get("top_exit_reason", "-")
    res["peak_age_candles"] = inv.get("peak_age_candles", 0)

    stage = str(res.get("stage", "IGNORE"))
    inv_class = str(inv.get("class", ""))
    inv_decision = str(inv.get("decision", ""))

    if stage != "SIGNAL":
        can_promote, promote_reason = _invisible_face_can_promote_to_signal(res, inv, stage)
        if can_promote:
            res["stage"] = "SIGNAL"
            res["score"] = round(max(safe_float(res.get("score", 0)), MIN_SIGNAL_SCORE + 1), 2)
            res["signal_label"] = "SHORT AL"
            res["reason"] = (
                f"{res.get('reason', '')} | FIRSAT KAÇIRMA FIX: {stage} → SIGNAL; {promote_reason}. "
                f"Not: riskli/takip değil, tek dış mesaj SHORT AL."
            )[:1400]
            stats["invisible_face_promote"] += 1
            if inv_class == "TEMİZ SHORT AL":
                stats["invisible_face_clean"] += 1
            return res

        if inv.get("watch_only"):
            stats["invisible_face_watch"] += 1
        res["signal_label"] = "İÇ TAKİP"
        return res

    if not inv.get("short_allowed"):
        res["stage"] = "READY" if inv.get("watch_only") else "HOT"
        res["score"] = round(max(0.0, safe_float(res.get("score", 0)) - 9.0), 2)
        res["reason"] = f"{res.get('reason', '')} | Görünmeyen yüz kapısı SHORT AL kilitledi: {inv_class} - {inv.get('islem_alinabilir_mi')}"
        stats["invisible_face_downgrade"] += 1
        stats["invisible_face_block"] += 1
        res["signal_label"] = "İÇ TAKİP"
        return res

    # Riskli scalp/takip sınıfları hâlâ dışarı sinyal değildir.
    if inv_class in ("RİSKLİ TP1 SCALP", "SHORT AV TAKİP", "AV YOK", "BLOK") or inv_decision in ("TP1_SCALP_SERBEST", "TAKİP", "SUS", "AL_YOK"):
        res["stage"] = "READY"
        res["score"] = round(max(0.0, safe_float(res.get("score", 0)) - 6.0), 2)
        res["reason"] = f"{res.get('reason', '')} | Riskli/takip sınıfı otomatik SHORT AL değildir: {inv_class}"
        stats["invisible_face_downgrade"] += 1
        res["signal_label"] = "İÇ TAKİP"
        return res

    stats["invisible_face_clean"] += 1
    res["signal_label"] = "SHORT AL"
    return res

def format_invisible_face_block(res: Dict[str, Any]) -> str:
    inv = res.get("invisible_face")
    if not inv or not inv.get("enabled"):
        return ""

    reasons = inv.get("reasons", [])
    reason_txt = " | ".join(str(x) for x in reasons[:5]) if reasons else "Nötr."

    return (
        "\n\n🕶️ GÖRÜNMEYEN YÜZ / LİKİDİTE AVI\n"
        f"🎯 Av nerede: {inv.get('av_nerede', '-')}\n"
        f"💧 Likidite nerede: {inv.get('likidite_nerede', '-')}\n"
        f"👥 Küçük yatırımcı nereye çekildi: {inv.get('kucuk_yatirimci_nerede', '-')}\n"
        f"🪤 Tuzak: {inv.get('tuzak', '-')}\n"
        f"🎣 Tepe/stop hunt: {inv.get('tepe_stop_hunt', '-')}\n"
        f"🐋 Büyük para izi: {inv.get('buyuk_para_izi', '-')}\n"
        f"📍 Dağıtım nerede: {inv.get('dagitim_nerede', '-')}\n"
        f"🧱 Orderbook izi: {inv.get('orderbook_izi', '-')}\n"
        f"⚔️ Trade flow izi: {inv.get('trade_flow_izi', '-')}\n"
        f"🧹 Fiyat nereye süpürülür: {inv.get('supurme_hedefi', '-')}\n"
        f"⏱️ İşlem hâlâ alınabilir mi: {inv.get('islem_alinabilir_mi', '-')}\n"
        f"🎯 TP1 gerçekçi mi: {inv.get('tp1_gercekci_mi', '-')}\n"
        f"🛡️ Stop mantıklı mı: {inv.get('stop_mantikli_mi', '-')}\n"
        f"🧠 EMA/RSI: {inv.get('ema_rsi_durumu', '-')}\n"
        f"🧬 Görünmeyen yüz skoru: {inv.get('score', 0)}/100 | Sınıf: {inv.get('class', '-')}\n"
        f"⏳ Tepe erken okuma: {'AKTİF' if inv.get('top_early_short') else '-'} | skor {inv.get('top_exit_score', 0)} | sebep: {inv.get('top_exit_reason', '-')}\n"
        f"📌 Son karar: {inv.get('decision', '-')}\n"
        f"Not: {reason_txt}"
    )


async def confirm_signal_on_binance(res: Dict[str, Any]) -> Dict[str, Any]:
    if not BINANCE_CONFIRM_ENABLED:
        return {
            "status": "DISABLED",
            "score": 0.0,
            "price_gap_pct": 0.0,
            "binance_symbol": normalize_binance_symbol(res["symbol"]),
            "binance_price": 0.0,
            "reason": "Binance teyidi kapalı.",
        }

    symbol = normalize_binance_symbol(res["symbol"])
    k1 = await get_binance_klines(symbol, "1m", 80)
    k5 = await get_binance_klines(symbol, "5m", 80)
    if len(k1) < 30 or len(k5) < 30:
        return {
            "status": "UNAVAILABLE",
            "score": 0.0,
            "price_gap_pct": 0.0,
            "binance_symbol": symbol,
            "binance_price": 0.0,
            "reason": "Binance teyit verisi yok.",
        }

    c1 = closes(k1)
    c5 = closes(k5)
    h1 = highs(k1)
    l1 = lows(k1)

    ema9_1 = ema(c1, 9)
    ema21_1 = ema(c1, 21)
    rsi1 = rsi(c1, 14)
    rsi5 = rsi(c5, 14)

    last_price = c1[-1]
    prev_price = c1[-2]
    okx_price = safe_float(res.get("price", 0))
    price_gap_pct = abs(pct_change(okx_price, last_price)) if okx_price > 0 and last_price > 0 else 0.0

    last_kline = k1[-1]
    prev_kline = k1[-2]
    weak_close = last_price <= safe_float(prev_kline[3]) or last_price < safe_float(last_kline[1])
    bear_cross = ema9_1[-1] < ema21_1[-1] and ema9_1[-2] >= ema21_1[-2]
    micro_bear = last_price < prev_price and last_price < ema9_1[-1]
    rej_score = candle_rejection_score(last_kline)
    # V5.2.7.2 fix: kapalı mumlardan pump ölç
    pump_20m = pct_change(min(c1[-21:-1]), last_price) if len(c1) >= 22 else pct_change(min(c1[:-1]), last_price)
    pump_10m = pct_change(min(c1[-11:-1]), last_price) if len(c1) >= 12 else pct_change(min(c1[:-1]), last_price)
    structure_turn = lower_highs(h1, 3) and lower_lows(l1, 3)
    red_count_5 = recent_red_count(k1, 5)
    breakdown = short_breakdown_confirmation(k1, k5)
    trend_guard = trend_continuation_guard(
        pump_10m=pump_10m,
        pump_20m=pump_20m,
        last_price=last_price,
        ema9=ema9_1[-1],
        ema21=ema21_1[-1],
        rsi1_val=rsi1[-1],
        rsi5_val=rsi5[-1],
        rej_score=rej_score,
        weak_close=weak_close,
        structure_turn=structure_turn,
        breakdown_score=breakdown["score"],
        red_count=red_count_5,
    )

    score = 0.0
    reasons: List[str] = []

    if price_gap_pct <= MAX_BINANCE_OKX_PRICE_GAP_PCT:
        score += 6.0
        reasons.append(f"Fiyat farkı iyi %{price_gap_pct:.2f}")
    elif price_gap_pct <= HARD_BINANCE_OKX_PRICE_GAP_PCT:
        score -= 2.0
        reasons.append(f"Fiyat farkı orta %{price_gap_pct:.2f}")
    else:
        score -= 16.0
        reasons.append(f"Fiyat farkı yüksek %{price_gap_pct:.2f}")

    if micro_bear:
        score += 4.0
        reasons.append("Binance 1dk zayıflıyor")
    if bear_cross:
        score += 5.0
        reasons.append("Binance EMA9/21 aşağı")
    if last_price < ema9_1[-1]:
        score += 4.0
        reasons.append("Binance EMA9 altı")
    if last_price < ema21_1[-1]:
        score += 4.0
        reasons.append("Binance EMA21 altı")
    if rsi1[-1] < 50:
        score += 4.0
        reasons.append("Binance RSI1 gevşek")
    elif rsi1[-1] < 54:
        score += 2.0
        reasons.append("Binance RSI1 sarkıyor")
    if weak_close:
        score += 4.0
        reasons.append("Binance zayıf kapanış")
    if c5[-1] < c5[-2] and c5[-1] < c5[-3]:
        score += 4.0
        reasons.append("Binance 5dk gevşeme")
    if rej_score >= 10:
        score += 3.0
        reasons.append("Binance iğne/red")
    if structure_turn:
        score += 3.0
        reasons.append("Binance yapı dönüyor")
    if breakdown["score"] >= TREND_BREAKDOWN_MIN_SCORE:
        score += 4.0
        reasons.append(f"Binance kırılım teyidi {breakdown['score']:.1f}")

    if trend_guard["blocked"]:
        score -= 12.0
        reasons.append(f"Binance trend devam kilidi: {trend_guard['reason']}")

    if pump_20m > 2.6 and last_price > ema9_1[-1] > ema21_1[-1] and rsi1[-1] > 61 and rsi5[-1] > 62 and not weak_close:
        score -= 8.0
        reasons.append("Binance trend hâlâ güçlü")

    if price_gap_pct > HARD_BINANCE_OKX_PRICE_GAP_PCT:
        status = "HARD_FAIL"
    elif trend_guard["blocked"] and breakdown["score"] < TREND_BREAKDOWN_MIN_SCORE:
        status = "FAIL"
    elif score >= BINANCE_CONFIRM_SCORE_PASS:
        status = "PASS"
    elif score >= BINANCE_CONFIRM_SCORE_SOFT:
        status = "SOFT_PASS"
    else:
        status = "FAIL"

    return {
        "status": status,
        "score": round(score, 2),
        "price_gap_pct": round(price_gap_pct, 2),
        "binance_symbol": symbol,
        "binance_price": last_price,
        "reason": " | ".join(reasons[:8]) if reasons else "Binance teyit nedeni yok.",
    }


def update_trend_watch(symbol: str, res: Dict[str, Any], guard: Dict[str, Any], breakdown: Dict[str, Any]) -> None:
    watch = memory.setdefault("trend_watch", {})
    rec = watch.get(symbol, {})
    first_price = safe_float(rec.get("first_price", 0)) or safe_float(res.get("price", 0))
    watch[symbol] = {
        "first_seen": rec.get("first_seen", time.time()),
        "last_seen": time.time(),
        "first_price": first_price,
        "last_price": res.get("price"),
        "score": res.get("score", 0),
        "guard_score": guard.get("score", 0),
        "breakdown_score": breakdown.get("score", 0),
        "reason": guard.get("reason", ""),
        "updates": int(rec.get("updates", 0)) + 1,
    }


def apply_breakdown_candidate_assist(
    symbol: str,
    candidate_score: float,
    ready_score: float,
    verify_score: float,
    breakdown_score: float,
    breakdown_reason: str,
    reasons: List[str],
) -> Tuple[float, float, float]:
    """
    Kırılım teyidi alan coin, aday puanı düşük diye çöpe düşmesin.
    V5.2.7.1'te bu destek V5.3.3.2'den daha dengeli çalışır.
    """
    if not BREAKDOWN_ASSIST_ENABLED:
        return candidate_score, ready_score, verify_score

    if breakdown_score < BREAKDOWN_ASSIST_MIN_SCORE:
        return candidate_score, ready_score, verify_score

    stats["breakdown_candidate_assist"] += 1

    if candidate_score < BREAKDOWN_ASSIST_CANDIDATE_FLOOR:
        old_candidate = candidate_score
        candidate_score = BREAKDOWN_ASSIST_CANDIDATE_FLOOR
        reasons.append(
            f"Kırılım aday kapısını açtı: aday {old_candidate:.1f}->{candidate_score:.1f}, kırılım {breakdown_score:.1f}"
        )

    current_ready_total = candidate_score + ready_score
    if current_ready_total < BREAKDOWN_ASSIST_READY_FLOOR:
        add_ready = BREAKDOWN_ASSIST_READY_FLOOR - current_ready_total
        ready_score += add_ready
        reasons.append(f"Kırılım READY desteği +{add_ready:.1f}: {breakdown_reason}")

    if breakdown_score >= BREAKDOWN_ASSIST_STRONG_SCORE:
        verify_score += BREAKDOWN_ASSIST_STRONG_VERIFY_BONUS
        reasons.append(f"Güçlü kırılım final desteği +{BREAKDOWN_ASSIST_STRONG_VERIFY_BONUS:.1f}")
    else:
        verify_score += BREAKDOWN_ASSIST_VERIFY_BONUS
        reasons.append(f"Kırılım final desteği +{BREAKDOWN_ASSIST_VERIFY_BONUS:.1f}")

    return candidate_score, ready_score, verify_score


def hot_memory_bonus(symbol: str, price: float) -> Tuple[float, float, float, List[str]]:
    rec = memory.get("hot", {}).get(symbol, {})
    if not rec:
        return 0.0, 0.0, 0.0, []
    updates = int(rec.get("updates", 0))
    prev_best = safe_float(rec.get("score", 0))
    first_price = safe_float(rec.get("first_price", 0))
    last_price = safe_float(rec.get("last_price", 0))
    reasons: List[str] = []

    cand_bonus = 0.0
    ready_bonus = 0.0
    verify_bonus = 0.0

    if updates >= 2:
        cand_bonus += 2.0
        ready_bonus += 2.0
        reasons.append("Sıcak hafıza devam")
    if updates >= 4:
        ready_bonus += 2.0
        verify_bonus += 1.0
        reasons.append("Takipte tekrar teyit")
    if prev_best >= MIN_READY_SCORE:
        verify_bonus += 2.0
        reasons.append("Önceki güçlü skor izi")
    if first_price > 0 and price > 0:
        rise_from_first = pct_change(first_price, price)
        if rise_from_first >= 1.0:
            cand_bonus += 1.0
            ready_bonus += 1.0
            reasons.append("İzlemden sonra ekstra şişme")
    if last_price > 0 and price > 0 and price < last_price:
        verify_bonus += 1.0
        reasons.append("Sıcak coin geri kıvırıyor")

    return cand_bonus, ready_bonus, verify_bonus, reasons


# =========================================================
# ANALİZ
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

    c1 = closes(k1)
    c5 = closes(k5)
    c15 = closes(k15)
    h1 = highs(k1)
    l1 = lows(k1)
    v1 = volumes(k1)
    v5 = volumes(k5)

    ema9_1 = ema(c1, 9)
    ema21_1 = ema(c1, 21)
    ema50_5 = ema(c5, 50)
    rsi1 = rsi(c1, 14)
    rsi5 = rsi(c5, 14)
    rsi15 = rsi(c15, 14)
    atr1 = atr(k1, 14)
    atr5 = atr(k5, 14)

    last_price = c1[-1]
    prev_price = c1[-2]
    last_rsi1 = rsi1[-1]
    prev_rsi1 = rsi1[-2]
    last_rsi5 = rsi5[-1]
    last_rsi15 = rsi15[-1]
    last_ema9_1 = ema9_1[-1]
    last_ema21_1 = ema21_1[-1]
    last_ema50_5 = ema50_5[-1]
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

    # V5.2.7.2 fix: pump hesabında canlı mumu hariç tut (kapalı mumlardan ölç)
    pump_10m = pct_change(min(c1[-11:-1]), last_price) if len(c1) >= 12 else pct_change(min(c1[:-1]), last_price)
    pump_20m = pct_change(min(c1[-21:-1]), last_price) if len(c1) >= 22 else pct_change(min(c1[:-1]), last_price)
    pump_1h = pct_change(min(c5[-13:-1]), last_price) if len(c5) >= 14 else pct_change(min(c5[:-1]), last_price)
    dist_from_ema21 = pct_change(last_ema21_1, last_price)
    vol_ratio_1m = safe_float(v1[-1]) / max(avg(v1[-20:-1]), 1e-9)
    vol_ratio_5m = safe_float(v5[-1]) / max(avg(v5[-12:-1]), 1e-9)

    recent_high_20 = max(h1[-21:-1])
    last_kline = k1[-1]
    prev_kline = k1[-2]
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

    trend_guard = trend_continuation_guard(
        pump_10m=pump_10m,
        pump_20m=pump_20m,
        last_price=last_price,
        ema9=last_ema9_1,
        ema21=last_ema21_1,
        rsi1_val=last_rsi1,
        rsi5_val=last_rsi5,
        rej_score=rej_score,
        weak_close=weak_close,
        structure_turn=structure_turn,
        breakdown_score=breakdown_score,
        red_count=red_count_5,
    )

    strong_breakout_continue = (
        pump_20m > 2.8 and
        last_price > last_ema9_1 > last_ema21_1 and
        last_rsi1 > 66 and
        last_rsi5 > 66 and
        rej_score < 10 and
        not weak_close and
        not structure_turn and
        breakdown_score < TREND_BREAKDOWN_MIN_SCORE
    )

    candidate_score = 0.0
    ready_score = 0.0
    verify_score = 0.0
    reasons: List[str] = []

    if pump_10m >= 0.8:
        candidate_score += 9
        reasons.append(f"10dk pump %{pump_10m:.2f}")
    if pump_20m >= 1.35:
        candidate_score += 11
        reasons.append(f"20dk pump %{pump_20m:.2f}")
    if pump_1h >= 2.5:
        candidate_score += 10
        reasons.append(f"1s pump %{pump_1h:.2f}")
    if last_rsi5 >= 64:
        candidate_score += 9
        reasons.append(f"5dk RSI {last_rsi5:.1f}")
    if dist_from_ema21 >= 0.55:
        candidate_score += 9
        reasons.append(f"EMA21 üstü %{dist_from_ema21:.2f}")
    if vol_ratio_1m >= 1.45:
        candidate_score += 8
        reasons.append(f"1dk hacim x{vol_ratio_1m:.2f}")
    if vol_ratio_5m >= 1.25:
        candidate_score += 6
        reasons.append(f"5dk hacim x{vol_ratio_5m:.2f}")

    if rej_score >= 10:
        ready_score += clamp(rej_score, 0, 18)
        reasons.append(f"İğne/red {rej_score:.1f}")
    if failed_breakout:
        ready_score += 13
        reasons.append("Sahte kırılım")
    if micro_bear:
        ready_score += 9
        reasons.append("1dk zayıf kapanış")
    if bear_cross:
        ready_score += 9
        reasons.append("EMA9/21 kısa zayıflama")
    if losing_momentum:
        ready_score += 7
        reasons.append("RSI momentum düşüşü")
    if structure_turn:
        ready_score += 10
        reasons.append("Alt yapı bozuluyor")

    if last_price < last_ema9_1:
        verify_score += 10
        reasons.append("Fiyat EMA9 altı")
    if last_price < last_ema21_1:
        verify_score += 8
        reasons.append("Fiyat EMA21 altı")
    if last_rsi1 < 50:
        verify_score += 8
        reasons.append("1dk RSI 50 altı")
    elif last_rsi1 < 54:
        verify_score += 4
        reasons.append("1dk RSI gevşiyor")
    if weak_close:
        verify_score += 8
        reasons.append("Zayıf son mum")
    if c5[-1] < c5[-2] and c5[-1] < c5[-3]:
        verify_score += 8
        reasons.append("5dk gevşeme")
    if last_rsi15 >= 56:
        verify_score += 5
        reasons.append("15dk hâlâ şişkin")
    if last_price > last_ema50_5:
        verify_score += 4
        reasons.append("5dk EMA50 üstünde, dönüş alanı var")

    if breakdown_score >= TREND_BREAKDOWN_MIN_SCORE:
        verify_score += 9
        stats["trend_breakdown_pass"] += 1
        reasons.append(f"Short kırılım teyidi {breakdown_score:.1f}: {breakdown.get('reason', '')}")
    elif breakdown_score >= TREND_BREAKDOWN_MIN_SCORE * 0.65:
        verify_score += 3
        reasons.append(f"Kırılım yarım {breakdown_score:.1f}: {breakdown.get('reason', '')}")

    cand_bonus, ready_bonus, verify_bonus, bonus_reasons = hot_memory_bonus(symbol, last_price)
    candidate_score += cand_bonus
    ready_score += ready_bonus
    verify_score += verify_bonus
    reasons.extend(bonus_reasons)

    if pump_10m < 0.55 and pump_20m < 1.0:
        candidate_score -= 4
        reasons.append("Pump zayıf")
    if vol_ratio_1m < 0.95 and vol_ratio_5m < 0.95:
        ready_score -= 3
        reasons.append("Hacim sönük")
    if last_rsi15 < 49:
        candidate_score -= 3
        reasons.append("15dk çok şişkin değil")

    if green_streak >= 3 and breakdown_score < TREND_BREAKDOWN_MIN_SCORE:
        verify_score -= 7
        reasons.append(f"Yeşil seri devam {green_streak}, short erken")

    candidate_score, ready_score, verify_score = apply_breakdown_candidate_assist(
        symbol=symbol,
        candidate_score=candidate_score,
        ready_score=ready_score,
        verify_score=verify_score,
        breakdown_score=breakdown_score,
        breakdown_reason=str(breakdown.get("reason", "")),
        reasons=reasons,
    )

    # ICT PRO SHORT bağlamı: mevcut balina/akış motorunun üstüne ayrı yapı/bölge teyidi verir.
    if SHORT_ICT_CONTEXT_ENABLED and isinstance(ict_context, dict) and ict_context.get("enabled"):
        short_ict_score = safe_float(ict_context.get("short_pro_score", 0))
        long_ict_score = safe_float(ict_context.get("long_pro_score", 0))
        if short_ict_score >= ICT_SHORT_MIN_PRO_SCORE:
            candidate_score += 6
            ready_score += 5
            verify_score += 4
            reasons.append(f"ICT PRO SHORT onayı {short_ict_score:.1f}: {ict_context.get('short_pro_reason', '-')}")
        elif short_ict_score >= ICT_SHORT_MIN_PRO_SCORE * 0.65:
            ready_score += 3
            verify_score += 2
            reasons.append(f"ICT PRO yarım short bağlamı {short_ict_score:.1f}: {ict_context.get('short_pro_reason', '-')}")
        if ict_context.get("in_premium_zone") or ict_context.get("above_equilibrium"):
            candidate_score += 2
        if ict_context.get("sweep_high"):
            ready_score += 4
            reasons.append("ICT üst likidite süpürme")
        if ict_context.get("choch_down") or ict_context.get("bos_down") or ict_context.get("mss_down"):
            verify_score += 4
            reasons.append("ICT BOS/CHOCH/MSS aşağı")
        if ict_context.get("bearish_ob_near"):
            ready_score += 2
            reasons.append("ICT bearish order block yakın")
        if ict_context.get("bearish_fvg_active"):
            verify_score += 2
            reasons.append("ICT bearish FVG aktif")
        # Talep/discount tarafında short basma hatasını azaltır.
        if (ict_context.get("in_discount_zone") or ict_context.get("sweep_low")) and long_ict_score > short_ict_score + 1.5:
            candidate_score -= 6
            ready_score -= 5
            verify_score -= 4
            reasons.append(f"ICT PRO short karşıtı: long bağlamı baskın {long_ict_score:.1f}>{short_ict_score:.1f}")

    candidate_score = max(candidate_score, 0.0)
    ready_score = max(ready_score, 0.0)
    verify_score = max(verify_score, 0.0)
    total_score = candidate_score + ready_score + verify_score

    entry = last_price
    stop, tp1, tp2, tp3, rr = calculate_short_levels(entry, h1, last_atr1, last_atr5)

    base_payload = {
        "symbol": symbol,
        "stage": "HOT",
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
        "vol_ratio_1m": round(vol_ratio_1m, 2),
        "vol_ratio_5m": round(vol_ratio_5m, 2),
        "quote_volume": quote_vol,
        "trend_guard_score": safe_float(trend_guard.get("score", 0)),
        "breakdown_score": breakdown_score,
        "green_streak": green_streak,
        "red_count_5": red_count_5,
        "quality_score": 0.0,
        "quality_reason": "-",
        "reason": " | ".join(reasons[:10]) if reasons else "Sebep yok",
        "ict": ict_context,
    }

    possible_top_reversal_hint = (
        failed_breakout
        or micro_bear
        or bear_cross
        or losing_momentum
        or weak_close
        or structure_turn
        or rej_score >= 10
        or breakdown_score >= FIRST_BREAK_MIN_BREAKDOWN_SCORE
        or red_count_5 >= 1
    )

    if (strong_breakout_continue or trend_guard.get("blocked")) and not possible_top_reversal_hint:
        stats["trend_strong_reject"] += 1
        stats["trend_guard_block_signal"] += 1
        stats["trend_guard_watch"] += 1
        base_payload["stage"] = "HOT"
        base_payload["score"] = round(max(total_score, MIN_CANDIDATE_SCORE), 2)
        base_payload["reason"] = (
            f"TREND DEVAM KORUMASI: Yükseliş bozulmadı, short erken. "
            f"Trend: {trend_guard.get('reason', '')} | Kırılım: {breakdown.get('reason', '')} | "
            f"Eski nedenler: {base_payload['reason']}"
        )[:900]
        update_trend_watch(symbol, copy.deepcopy(base_payload), trend_guard, breakdown)
        return base_payload
    elif strong_breakout_continue or trend_guard.get("blocked"):
        reasons.append("Trend koruması uyardı ama tepe/red ihtimali var; görünmeyen yüz motoruna bırakıldı")

    if candidate_score < MIN_CANDIDATE_SCORE:
        stats["weak_candidate_reject"] += 1
        stage = "IGNORE"
    elif (candidate_score + ready_score) < MIN_READY_SCORE:
        stage = "HOT"
        stats["hot_add"] += 1
    elif total_score < MIN_SIGNAL_SCORE:
        stage = "READY"
        stats["weak_signal_reject"] += 1
    else:
        stage = "SIGNAL"

    if stage == "SIGNAL" and breakdown_score < TREND_BREAKDOWN_MIN_SCORE:
        weak_breakdown_top_context = (
            (failed_breakout or rej_score >= 16 or weak_close or micro_bear or structure_turn or red_count_5 >= 1)
            and (pump_20m >= TEPE_ERKEN_MIN_PUMP_20M or pump_1h >= TEPE_ERKEN_MIN_PUMP_1H)
            and breakdown_score >= TEPE_ERKEN_PROMOTE_MIN_BREAKDOWN_SCORE
        )
        if weak_breakdown_top_context:
            total_score -= 2
            reasons.append(f"FIRSAT KAÇIRMA FIX: tepe/red bağlamında tam kırılım beklenmedi {breakdown_score:.1f}/{TREND_BREAKDOWN_MIN_SCORE:.1f}")
        else:
            stage = "READY"
            total_score -= 8
            stats["trend_guard_block_signal"] += 1
            reasons.append(f"SHORT kilitlendi: yapı bozulması yetersiz {breakdown_score:.1f}/{TREND_BREAKDOWN_MIN_SCORE:.1f}")

    if stage == "SIGNAL" and rr < MIN_RR_TP1:
        stage = "READY"
        total_score -= 6
        stats["rr_block"] += 1
        reasons.append(f"RR zayıf {rr:.2f}, sinyal düşürüldü")

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
        "vol_ratio_1m": round(vol_ratio_1m, 2),
        "vol_ratio_5m": round(vol_ratio_5m, 2),
        "quote_volume": quote_vol,
        "trend_guard_score": safe_float(trend_guard.get("score", 0)),
        "breakdown_score": breakdown_score,
        "green_streak": green_streak,
        "red_count_5": red_count_5,
        "quality_score": 0.0,
        "quality_reason": "-",
        "reason": " | ".join(reasons[:12]) if reasons else "Sebep yok",
        "ict": ict_context,
    }

    final_payload["invisible_face"] = await build_invisible_face_short(
        symbol=symbol,
        payload=final_payload,
        k1=k1,
        k5=k5,
        k15=k15,
        failed_breakout=failed_breakout,
        micro_bear=micro_bear,
        bear_cross=bear_cross,
        losing_momentum=losing_momentum,
        weak_close=weak_close,
        structure_turn=structure_turn,
        rej_score=rej_score,
        breakdown_reason=str(breakdown.get("reason", "")),
    )
    final_payload = apply_invisible_face_gate(final_payload)

    if final_payload["stage"] == "SIGNAL":
        close_gate = short_close_confirmation_gate(k5, k15, final_payload)
        final_payload["close_confirm_gate"] = close_gate
        final_payload["reason"] = f"{final_payload.get('reason', '')} | 5m/15m kapanış kapısı: {close_gate.get('reason', '-')}"[:1400]
        if not close_gate.get("passed", False):
            final_payload["stage"] = "READY"
            final_payload["score"] = round(safe_float(final_payload.get("score", 0)) - 6, 2)
            stats["close_confirm_block"] += 1
            update_hot_memory({**copy.deepcopy(final_payload), "stage": "READY", "reason": f"{final_payload.get('reason', '')} | 1m radar takipte; 5m/15m kapanış onayı bekleniyor."})
            return final_payload
        if close_gate.get("class") == "RISKY":
            early_close_exception = (
                TEPE_ERKEN_ALLOW_RISKY_CLOSE
                and bool(final_payload.get("top_early_short"))
                and str(final_payload.get("invisible_class", "")) in ("TEPE ERKEN SHORT", "TEMİZ SHORT AL")
                and safe_float(final_payload.get("invisible_score", 0)) >= TEPE_ERKEN_PROMOTE_MIN_INVISIBLE_SCORE
                and safe_float(final_payload.get("breakdown_score", 0)) >= TEPE_ERKEN_PROMOTE_MIN_BREAKDOWN_SCORE
            )
            if not early_close_exception:
                final_payload["stage"] = "READY"
                final_payload["signal_label"] = "İÇ TAKİP"
                final_payload["score"] = round(safe_float(final_payload.get("score", 0)) - 5, 2)
                final_payload["reason"] = f"{final_payload.get('reason', '')} | TEK SHORT AL FIX: 5m/15m kapanış RISKY; otomatik SHORT AL iptal."
                stats["close_confirm_risky"] += 1
                update_hot_memory(copy.deepcopy(final_payload))
                return final_payload
            stats["close_confirm_risky"] += 1
            final_payload["reason"] = f"{final_payload.get('reason', '')} | FIRSAT KAÇIRMA FIX: 5m/15m RISKY ama tepe para çıkışı güçlü; SHORT AL korundu."[:1400]

    if final_payload["stage"] == "SIGNAL":
        passed, q_reason, q_score = final_quality_gate(final_payload)
        final_payload["quality_score"] = q_score
        final_payload["quality_reason"] = q_reason
        if not passed:
            final_payload["stage"] = "READY"
            final_payload["score"] = round(safe_float(final_payload["score"]) - 7, 2)
            stats["quality_gate_block"] += 1
            final_payload["reason"] = f"{final_payload['reason']} | Kalite kapısı kilitledi: {q_reason}"

    final_payload = enforce_single_short_al_rules(final_payload)
    return final_payload




# =========================================================
# AYRI LONG MOTORU - ICT DISCOUNT / LİKİDİTE SWEEP / TALEP
# =========================================================
async def analyze_long_symbol(symbol: str, tickers24: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    SHORT motorundan tamamen ayrı LONG motoru.
    Mantık: düşüş/pullback -> discount/0.5-0.618 talep bölgesi -> alt likidite sweep ->
    alıcı savunması -> CHOCH/BOS yukarı -> LONG AL.
    """
    if not LONG_ENGINE_ENABLED:
        return None

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
    if len(k1) < 60 or len(k5) < 60 or len(k15) < 50:
        stats["no_data"] += 1
        return None

    c1 = closes(k1); h1 = highs(k1); l1 = lows(k1); v1 = volumes(k1)
    c5 = closes(k5); h5 = highs(k5); l5 = lows(k5); v5 = volumes(k5)
    c15 = closes(k15)
    ema9_1 = ema(c1, 9); ema21_1 = ema(c1, 21)
    ema9_5 = ema(c5, 9); ema21_5 = ema(c5, 21); ema50_5 = ema(c5, 50)
    rsi1 = rsi(c1, 14); rsi5 = rsi(c5, 14); rsi15 = rsi(c15, 14)
    atr1 = atr(k1, 14); atr5 = atr(k5, 14)

    last_price = c1[-1]
    last_rsi1 = rsi1[-1]; prev_rsi1 = rsi1[-2]
    last_rsi5 = rsi5[-1]; last_rsi15 = rsi15[-1]
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

    ict = build_ict_zone_context(k1, k5, k15, last_price)
    if not ict.get("enabled"):
        return None
    if safe_float(ict.get("range_pct", 0)) < ICT_MIN_RANGE_PCT:
        stats["long_reject"] += 1
        return {
            "symbol": symbol, "direction": "LONG", "stage": "IGNORE", "score": 0,
            "price": last_price, "reason": f"ICT aralık zayıf %{ict.get('range_pct', 0)}"
        }

    book = await get_okx_orderbook(symbol)
    trades = await get_okx_recent_trades(symbol, 120)
    flow = analyze_trade_flow(trades)

    upper_wick, lower_wick, body_ratio, red = candle_wick_ratios(k1[-1])
    green = not red
    vol_ratio_1m = safe_float(v1[-1]) / max(avg(v1[-20:-1]), 1e-9)
    vol_ratio_5m = safe_float(v5[-1]) / max(avg(v5[-12:-1]), 1e-9)
    drop_10m = max(0.0, abs(pct_change(max(c1[-11:-1]), last_price))) if len(c1) >= 12 and last_price < max(c1[-11:-1]) else 0.0
    drop_20m = max(0.0, abs(pct_change(max(c1[-21:-1]), last_price))) if len(c1) >= 22 and last_price < max(c1[-21:-1]) else 0.0
    drop_1h = max(0.0, abs(pct_change(max(c5[-13:-1]), last_price))) if len(c5) >= 14 and last_price < max(c5[-13:-1]) else 0.0
    bounce_from_low = pct_change(min(l1[-20:]), last_price) if len(l1) >= 20 and min(l1[-20:]) > 0 else 0.0

    buy_to_sell = safe_float(flow.get("buy_to_sell", 0))
    sell_to_buy = safe_float(flow.get("sell_to_buy", 0))
    book_pressure = safe_float(book.get("book_pressure", 0))
    bid_wall_added = bool(book.get("bid_wall_added", False))
    ask_wall_pulled = bool(book.get("ask_wall_pulled", False))
    bid_defense = bool(book.get("ok")) and (bid_wall_added or ask_wall_pulled or book_pressure <= -0.12)
    buyer_defense = (
        lower_wick >= 0.28
        or buy_to_sell >= LONG_MIN_BUY_TO_SELL
        or bid_defense
        or (green and vol_ratio_1m >= 0.85)
    )

    structure = long_structure_confirmation(k1, k5, ict)
    structure_score = safe_float(structure.get("score", 0))
    close_gate = long_close_confirmation_gate(k5, k15)

    candidate_score = 0.0; ready_score = 0.0; verify_score = 0.0
    reasons: List[str] = []

    if drop_20m >= LONG_MIN_DROP_20M:
        candidate_score += 7; reasons.append(f"20dk geri çekilme %{drop_20m:.2f}")
    if drop_1h >= LONG_MIN_DROP_1H:
        candidate_score += 8; reasons.append(f"1s geri çekilme %{drop_1h:.2f}")
    if ict.get("in_discount_zone"):
        candidate_score += 12; reasons.append("ICT discount / 0.5-0.618 talep bölgesi")
    if ict.get("below_equilibrium"):
        candidate_score += 5; reasons.append("EQ altında ucuz bölge")
    if ict.get("sweep_low"):
        ready_score += 14; reasons.append("Alt likidite süpürüldü")
    if lower_wick >= 0.28:
        ready_score += 9; reasons.append(f"Alt fitil alıcı savunması {lower_wick:.2f}")
    if buyer_defense:
        ready_score += 8; reasons.append("Alıcı savunması başladı")
    if buy_to_sell >= LONG_MIN_BUY_TO_SELL:
        ready_score += 8; reasons.append(f"Agresif alış baskın x{buy_to_sell:.2f}")
    elif sell_to_buy >= 1.45:
        ready_score -= 8; reasons.append(f"Satıcı hâlâ baskın x{sell_to_buy:.2f}")
    if bid_defense:
        ready_score += 7; reasons.append("Orderbook bid savunması / ask çekilmesi")
    if ict.get("bullish_fvg") or ict.get("bullish_displacement"):
        ready_score += 6; reasons.append("Bullish FVG/displacement izi")
    if safe_float(ict.get("long_pro_score", 0)) >= ICT_LONG_MIN_PRO_SCORE:
        candidate_score += 6; ready_score += 5; verify_score += 3
        reasons.append(f"ICT PRO LONG onayı {safe_float(ict.get('long_pro_score', 0)):.1f}: {ict.get('long_pro_reason', '-')}")
    elif safe_float(ict.get("long_pro_score", 0)) >= ICT_LONG_MIN_PRO_SCORE * 0.65:
        ready_score += 3; verify_score += 2
        reasons.append(f"ICT PRO yarım long bağlamı {safe_float(ict.get('long_pro_score', 0)):.1f}: {ict.get('long_pro_reason', '-')}")
    if ict.get("bullish_ob_near"):
        ready_score += 4; reasons.append("ICT bullish order block / demand yakın")
    if ict.get("bullish_fvg_active"):
        verify_score += 3; reasons.append("ICT bullish FVG aktif")
    if ict.get("bos_up") or ict.get("choch_up") or ict.get("mss_up"):
        verify_score += 4; reasons.append("ICT BOS/CHOCH/MSS yukarı")
    if safe_float(ict.get("short_pro_score", 0)) > safe_float(ict.get("long_pro_score", 0)) + 1.5 and (ict.get("in_premium_zone") or ict.get("sweep_high")):
        candidate_score -= 6; ready_score -= 5; verify_score -= 4
        reasons.append(f"ICT PRO long karşıtı: short bağlamı baskın {safe_float(ict.get('short_pro_score', 0)):.1f}>{safe_float(ict.get('long_pro_score', 0)):.1f}")

    if structure_score >= ICT_MIN_CHOCH_SCORE:
        verify_score += 12; reasons.append(f"BOS/CHOCH yukarı {structure_score:.1f}: {structure.get('reason', '')}")
    elif structure_score >= ICT_MIN_CHOCH_SCORE * 0.70:
        verify_score += 5; reasons.append(f"Yarım yapı dönüşü {structure_score:.1f}: {structure.get('reason', '')}")
    if last_price > ema9_1[-1]:
        verify_score += 6; reasons.append("1dk EMA9 üstü")
    if last_price > ema21_1[-1]:
        verify_score += 5; reasons.append("1dk EMA21 üstü")
    if ema9_1[-1] > ema21_1[-1]:
        verify_score += 5; reasons.append("1dk EMA9/21 yukarı")
    if c5[-1] > c5[-2]:
        verify_score += 5; reasons.append("5dk kapanış toparlıyor")
    if last_rsi1 > prev_rsi1 and last_rsi1 >= 45:
        verify_score += 5; reasons.append("RSI yukarı dönüyor")
    if last_price > ema50_5[-1] and ict.get("in_discount_zone"):
        verify_score += 3; reasons.append("5dk EMA50 üstü talep korunuyor")

    # Long için risk kesen durumlar
    if ict.get("in_premium_zone") and not ict.get("in_discount_zone") and not ict.get("sweep_low"):
        candidate_score -= 8; reasons.append("Fiyat premium tarafta, long geç olabilir")
    if bounce_from_low > LONG_MAX_BOUNCE_FROM_LOW_PCT and not ict.get("sweep_low"):
        ready_score -= 7; reasons.append(f"Dipten fazla kaçmış %{bounce_from_low:.2f}")
    if last_rsi5 >= 72 and not ict.get("in_discount_zone"):
        verify_score -= 5; reasons.append("5dk RSI şişkin, long kovalamaya dönebilir")
    if vol_ratio_1m < 0.40 and vol_ratio_5m < 0.40:
        ready_score -= 4; reasons.append("Alım hacmi çok sönük")

    candidate_score = max(candidate_score, 0.0)
    ready_score = max(ready_score, 0.0)
    verify_score = max(verify_score, 0.0)
    total_score = candidate_score + ready_score + verify_score
    entry = last_price
    stop, tp1, tp2, tp3, rr = calculate_long_levels(entry, l1, last_atr1, last_atr5)

    quality_score = 0.0
    quality_notes: List[str] = []
    if ict.get("in_discount_zone"):
        quality_score += 1.4; quality_notes.append("discount bölge")
    if safe_float(ict.get("long_pro_score", 0)) >= ICT_LONG_MIN_PRO_SCORE:
        quality_score += 1.2; quality_notes.append("ICT PRO long bağlamı")
    if ict.get("sweep_low"):
        quality_score += 1.5; quality_notes.append("alt likidite sweep")
    if buyer_defense:
        quality_score += 1.2; quality_notes.append("alıcı savunması")
    if structure_score >= ICT_MIN_CHOCH_SCORE:
        quality_score += 1.4; quality_notes.append("CHOCH/BOS yukarı")
    if close_gate.get("passed"):
        quality_score += 1.0; quality_notes.append("kapanış teyidi")
    if buy_to_sell >= LONG_MIN_BUY_TO_SELL:
        quality_score += 0.8; quality_notes.append("trade flow alış")
    if rr >= LONG_MIN_RR_TP1:
        quality_score += 0.7; quality_notes.append("RR yeterli")
    if sell_to_buy >= 1.7:
        quality_score -= 1.2; quality_notes.append("satıcı hâlâ baskın")
    if bounce_from_low > LONG_MAX_BOUNCE_FROM_LOW_PCT:
        quality_score -= 0.8; quality_notes.append("dipten kaçmış")
    quality_score = round(clamp(quality_score, 0.0, 10.0), 2)

    if candidate_score < LONG_MIN_CANDIDATE_SCORE:
        stage = "IGNORE"
        stats["long_reject"] += 1
    elif total_score >= LONG_MIN_SIGNAL_SCORE and verify_score >= LONG_MIN_VERIFY_SCORE:
        stage = "SIGNAL"
    elif candidate_score + ready_score >= LONG_MIN_READY_SCORE:
        stage = "READY"
        stats["long_ready"] += 1
    else:
        stage = "HOT"
        stats["long_candidate"] += 1

    if stage == "SIGNAL" and rr < LONG_MIN_RR_TP1:
        stage = "READY"; stats["rr_block"] += 1; reasons.append(f"LONG RR zayıf {rr:.2f}")
    if stage == "SIGNAL" and not close_gate.get("passed", False):
        stage = "READY"; stats["long_close_confirm_block"] += 1; reasons.append(f"LONG kapanış kapısı bekliyor: {close_gate.get('reason', '-')}")
    if stage == "SIGNAL" and quality_score < LONG_MIN_QUALITY_SCORE:
        stage = "READY"; stats["long_quality_block"] += 1; reasons.append(f"LONG kalite zayıf {quality_score:.1f}: {' | '.join(quality_notes[:4])}")

    if stage == "SIGNAL":
        stats["long_ict_signal"] += 1

    payload = {
        "symbol": symbol,
        "direction": "LONG",
        "stage": stage,
        "signal_label": "LONG AL" if stage == "SIGNAL" else "İÇ TAKİP",
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
        "drop_10m": round(drop_10m, 2),
        "drop_20m": round(drop_20m, 2),
        "drop_1h": round(drop_1h, 2),
        "pump_10m": round(-drop_10m, 2),
        "pump_20m": round(-drop_20m, 2),
        "pump_1h": round(-drop_1h, 2),
        "rsi1": round(last_rsi1, 2),
        "rsi5": round(last_rsi5, 2),
        "rsi15": round(last_rsi15, 2),
        "vol_ratio_1m": round(vol_ratio_1m, 2),
        "vol_ratio_5m": round(vol_ratio_5m, 2),
        "quote_volume": quote_vol,
        "trend_guard_score": 0.0,
        "breakdown_score": structure_score,
        "long_structure_score": structure_score,
        "green_streak": consecutive_green_count(k1, 6),
        "red_count_5": recent_red_count(k1, 5),
        "quality_score": quality_score,
        "quality_reason": " | ".join(quality_notes[:8]) if quality_notes else "Long kalite notu yok",
        "reason": " | ".join(reasons[:16]) if reasons else "Long sebep yok",
        "ict": ict,
        "long_close_gate": close_gate,
        "trade_flow": flow,
        "orderbook": book,
        "invisible_class": "ICT LONG",
        "invisible_score": round(min(100.0, quality_score * 12.0 + structure_score * 4.0), 1),
        "invisible_decision": "LONG_AL_SERBEST" if stage == "SIGNAL" else "LONG_TAKIP",
    }
    return enforce_single_long_al_rules(payload)


def enforce_single_long_al_rules(payload: Dict[str, Any]) -> Dict[str, Any]:
    """LONG dış mesaj kapısı. LONG motoru ayrı olduğu için SHORT kuralları burada çalışmaz."""
    p = copy.deepcopy(payload)
    if p.get("stage") != "SIGNAL":
        return p
    ict = p.get("ict") if isinstance(p.get("ict"), dict) else {}
    reason = str(p.get("reason", ""))
    if ICT_REQUIRE_PRO_CONTEXT_FOR_SIGNAL and safe_float(ict.get("long_pro_score", 0)) < ICT_LONG_MIN_PRO_SCORE:
        p["stage"] = "READY"
        p["signal_label"] = "İÇ TAKİP"
        p["reason"] = f"{reason} | LONG ICT PRO: profesyonel bağlam skoru yetersiz {safe_float(ict.get('long_pro_score', 0)):.1f}/{ICT_LONG_MIN_PRO_SCORE:.1f}."
        stats["long_quality_block"] += 1
        return p
    if safe_float(p.get("long_structure_score", 0)) < ICT_MIN_CHOCH_SCORE and not (ict.get("bos_up") or ict.get("choch_up") or ict.get("mss_up")):
        p["stage"] = "READY"
        p["signal_label"] = "İÇ TAKİP"
        p["reason"] = f"{reason} | LONG ICT PRO: BOS/CHOCH/MSS yukarı yok."
        stats["long_quality_block"] += 1
        return p
    if not ict.get("in_discount_zone") and not ict.get("sweep_low"):
        p["stage"] = "READY"
        p["signal_label"] = "İÇ TAKİP"
        p["reason"] = f"{reason} | LONG FIX: discount/sweep yok, long kovalamaya dönmesin."
        stats["long_quality_block"] += 1
        return p
    if safe_float(p.get("quality_score", 0)) < LONG_MIN_QUALITY_SCORE:
        p["stage"] = "READY"
        p["signal_label"] = "İÇ TAKİP"
        p["reason"] = f"{reason} | LONG FIX: kalite zayıf."
        stats["long_quality_block"] += 1
        return p
    if safe_float(p.get("rr", 0)) < LONG_MIN_RR_TP1:
        p["stage"] = "READY"
        p["signal_label"] = "İÇ TAKİP"
        p["reason"] = f"{reason} | LONG FIX: RR zayıf."
        stats["rr_block"] += 1
        return p
    p["signal_label"] = "LONG AL"
    return p

def enforce_single_short_al_rules(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Son güvenlik kapısı.
    Dışarı otomatik gidebilecek tek mesaj SHORT AL'dir.
    RISKY kapanış, zayıf pump, riskli scalp veya çelişkili not varsa SIGNAL iptal edilir.
    """
    p = copy.deepcopy(payload)
    if p.get("stage") != "SIGNAL":
        return p

    reason_text = str(p.get("reason", ""))
    inv = p.get("invisible_face") if isinstance(p.get("invisible_face"), dict) else {}
    inv_class = str(p.get("invisible_class", inv.get("class", "")))
    inv_decision = str(p.get("invisible_decision", inv.get("decision", "")))
    pump_20m = safe_float(p.get("pump_20m", 0))
    pump_1h = safe_float(p.get("pump_1h", 0))
    close_class = str(p.get("close_confirm_gate", {}).get("class", "-"))

    ict = p.get("ict") if isinstance(p.get("ict"), dict) else {}
    if ICT_REQUIRE_PRO_CONTEXT_FOR_SIGNAL and ict.get("enabled") and safe_float(ict.get("short_pro_score", 0)) < ICT_SHORT_MIN_PRO_SCORE:
        p["stage"] = "READY"
        p["signal_label"] = "İÇ TAKİP"
        p["reason"] = f"{reason_text} | SHORT ICT PRO: profesyonel bağlam skoru yetersiz {safe_float(ict.get('short_pro_score', 0)):.1f}/{ICT_SHORT_MIN_PRO_SCORE:.1f}."
        stats["weak_signal_reject"] += 1
        return p
    if ict.get("enabled") and (ict.get("in_discount_zone") or ict.get("sweep_low")) and safe_float(ict.get("long_pro_score", 0)) > safe_float(ict.get("short_pro_score", 0)) + 1.5:
        p["stage"] = "READY"
        p["signal_label"] = "İÇ TAKİP"
        p["reason"] = f"{reason_text} | SHORT ICT PRO: discount/alt likidite long bağlamı baskın; short iptal."
        stats["weak_signal_reject"] += 1
        return p

    # 1) Pump zayıfsa otomatik sinyal yok.
    if pump_20m < 0.55 and pump_1h < 1.05:
        p["stage"] = "READY"
        p["signal_label"] = "İÇ TAKİP"
        p["reason"] = f"{reason_text} | TEK SHORT AL FIX: Pump bağlamı zayıf; otomatik SHORT AL iptal."
        stats["weak_signal_reject"] += 1
        return p

    if "Pump bağlamı zayıf" in reason_text or "Pump zayıf" in reason_text:
        p["stage"] = "READY"
        p["signal_label"] = "İÇ TAKİP"
        p["reason"] = f"{reason_text} | TEK SHORT AL FIX: Notta pump zayıf geçtiği için otomatik SHORT AL iptal."
        stats["weak_signal_reject"] += 1
        return p

    # 2) 5m/15m kapısı riskli ise Telegram'a SHORT AL gitmez.
    # İstisna: tepe erken motoru güçlü ve düşüş henüz kaçmamışsa RISKY kapanış SHORT AL'ı öldürmez.
    early_close_exception = (
        TEPE_ERKEN_ALLOW_RISKY_CLOSE
        and bool(p.get("top_early_short"))
        and close_class == "RISKY"
        and inv_class in ("TEPE ERKEN SHORT", "TEMİZ SHORT AL")
        and safe_float(p.get("invisible_score", 0)) >= TEPE_ERKEN_PROMOTE_MIN_INVISIBLE_SCORE
        and safe_float(p.get("breakdown_score", 0)) >= TEPE_ERKEN_PROMOTE_MIN_BREAKDOWN_SCORE
    )
    if close_class != "CLEAN" and not early_close_exception:
        p["stage"] = "READY"
        p["signal_label"] = "İÇ TAKİP"
        p["reason"] = f"{reason_text} | TEK SHORT AL FIX: 5m/15m kapanış CLEAN değil ({close_class}); otomatik SHORT AL iptal."
        stats["close_confirm_risky"] += 1
        return p

    # 3) Riskli görünmeyen yüz sınıfları otomatik sinyal değildir.
    bad_classes = ("RİSKLİ", "SCALP", "TAKİP", "AV YOK", "BLOK")
    if any(x in inv_class for x in bad_classes) or inv_decision in ("TP1_SCALP_SERBEST", "TAKİP", "SUS", "AL_YOK"):
        p["stage"] = "READY"
        p["signal_label"] = "İÇ TAKİP"
        p["reason"] = f"{reason_text} | TEK SHORT AL FIX: Görünmeyen yüz sınıfı dış sinyal değil ({inv_class}/{inv_decision})."
        stats["invisible_face_downgrade"] += 1
        return p

    # 4) Başlık/içerik çelişkisi olmasın.
    p["signal_label"] = "SHORT AL"
    p["risky_scalp_close_tp"] = False
    p["risky_scalp_tp_note"] = "-"
    p["reason"] = reason_text.replace("RİSKLİ SHORT AL", "SHORT AL").replace("RİSKLİ TP1 SCALP", "iç takip")
    return p


# =========================================================
# MEMORY / COOLDOWN
# =========================================================
def signal_key(symbol: str, stage: str) -> str:
    return f"{symbol}:{stage}"


def get_signal_record(symbol: str, stage: str) -> Dict[str, Any]:
    return memory.get("signals", {}).get(signal_key(symbol, stage), {})


def setup_record(symbol: str) -> Dict[str, Any]:
    return memory.get("signals", {}).get(f"setup:{symbol}", {})


def setup_in_cooldown(symbol: str) -> bool:
    rec = setup_record(symbol)
    ts = safe_float(rec.get("ts", 0))
    return time.time() - ts < SETUP_COOLDOWN_MIN * 60


def better_than_previous(symbol: str, stage: str, payload: Dict[str, Any]) -> bool:
    prev = get_signal_record(symbol, stage)
    prev_score = safe_float(prev.get("score", 0))
    prev_price = safe_float(prev.get("price", 0))
    cur_score = safe_float(payload.get("score", 0))
    cur_price = safe_float(payload.get("price", 0))

    price_move_pct = abs(pct_change(prev_price, cur_price)) if prev_price > 0 and cur_price > 0 else 0.0
    if cur_score >= prev_score + SCORE_OVERRIDE_GAP:
        return True
    if cur_score >= prev_score + (SCORE_OVERRIDE_GAP * 0.7) and price_move_pct >= PRICE_OVERRIDE_MOVE_PCT:
        return True
    return False


def daily_short_record(symbol: str, day_key: Optional[str] = None) -> Dict[str, Any]:
    return memory.get("daily_short_sent", {}).get(day_key or tr_day_key(), {}).get(symbol, {})


def daily_short_already_sent(symbol: str, day_key: Optional[str] = None) -> bool:
    return bool(daily_short_record(symbol, day_key))


def set_daily_short_sent(symbol: str, payload: Dict[str, Any]) -> None:
    day_key = tr_day_key()
    daily = memory.setdefault("daily_short_sent", {}).setdefault(day_key, {})
    daily[symbol] = {
        "ts": time.time(),
        "score": payload.get("score"),
        "price": payload.get("price"),
        "reason": payload.get("reason", ""),
    }


def get_today_short_sent_count() -> int:
    return len(memory.get("daily_short_sent", {}).get(tr_day_key(), {}))


def daily_long_record(symbol: str, day_key: Optional[str] = None) -> Dict[str, Any]:
    return memory.get("daily_long_sent", {}).get(day_key or tr_day_key(), {}).get(symbol, {})


def daily_long_already_sent(symbol: str, day_key: Optional[str] = None) -> bool:
    return bool(daily_long_record(symbol, day_key))


def set_daily_long_sent(symbol: str, payload: Dict[str, Any]) -> None:
    day_key = tr_day_key()
    daily = memory.setdefault("daily_long_sent", {}).setdefault(day_key, {})
    daily[symbol] = {
        "ts": time.time(),
        "score": payload.get("score"),
        "price": payload.get("price"),
        "reason": payload.get("reason", ""),
    }


def get_today_long_sent_count() -> int:
    return len(memory.get("daily_long_sent", {}).get(tr_day_key(), {}))


def daily_trade_already_sent(symbol: str, direction: str) -> bool:
    direction = (direction or "SHORT").upper()
    if direction == "LONG":
        return daily_long_already_sent(symbol)
    return daily_short_already_sent(symbol)


def set_daily_trade_sent(symbol: str, payload: Dict[str, Any]) -> None:
    direction = str(payload.get("direction", "SHORT")).upper()
    if direction == "LONG":
        set_daily_long_sent(symbol, payload)
    else:
        set_daily_short_sent(symbol, payload)


def get_today_trade_sent_count(direction: str) -> int:
    direction = (direction or "SHORT").upper()
    return get_today_long_sent_count() if direction == "LONG" else get_today_short_sent_count()


def get_daily_trade_limit(direction: str) -> int:
    direction = (direction or "SHORT").upper()
    return LONG_DAILY_TOTAL_LIMIT if direction == "LONG" else DAILY_SHORT_TOTAL_LIMIT


def has_active_trade() -> bool:
    # HIZLI AV FIX: Varsayılan olarak yeni coin sinyalini susturmaz.
    # Bu takip sistemi sadece kullanıcı özellikle açarsa çalışır.
    if not ONE_ACTIVE_TRADE_MODE or ACTIVE_TRADE_BLOCK_SEC <= 0:
        return False
    now_ts = time.time()
    for rec in memory.get("follows", {}).values():
        if rec.get("done"):
            continue
        sent_ts = safe_float(rec.get("sent_ts", rec.get("created_ts", 0)))
        if sent_ts and now_ts - sent_ts < ACTIVE_TRADE_BLOCK_SEC:
            return True
    return False


def global_signal_gap_active() -> bool:
    # HIZLI AV FIX: 30 dakikalık global susturma kaldırıldı.
    # SIGNAL_SPACING_SEC=0 ise başka coin fırsatını engellemez.
    if SIGNAL_SPACING_SEC <= 0:
        return False
    last_sig = safe_float(memory.get("last_signal_ts", 0))
    return bool(last_sig and time.time() - last_sig < SIGNAL_SPACING_SEC)


def signal_rank_score(res: Dict[str, Any]) -> float:
    inv_bonus = safe_float(res.get("invisible_score", 0)) * 0.9
    inv_class = str(res.get("invisible_class", ""))
    if inv_class == "TEMİZ SHORT AL":
        inv_bonus += 18
    elif inv_class == "TEPE ERKEN SHORT":
        inv_bonus += 14
    elif inv_class == "RİSKLİ TP1 SCALP":
        inv_bonus += 8
    elif inv_class in ("BLOK", "AV YOK"):
        inv_bonus -= 30

    return (
        safe_float(res.get("score", 0))
        + inv_bonus
        + safe_float(res.get("quality_score", 0)) * 2.0
        + safe_float(res.get("breakdown_score", 0)) * 1.2
        + safe_float(res.get("rr", 0)) * 2.0
        - max(0.0, safe_float(res.get("trend_guard_score", 0)) - 5.0) * 1.5
        - max(0.0, safe_float(res.get("green_streak", 0)) - 2.0) * 2.0
    )


def select_best_signals(signals: List[Dict[str, Any]], limit: int = MAX_SIGNAL_PER_SCAN) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if not signals:
        return [], []
    ordered = sorted(signals, key=signal_rank_score, reverse=True)
    keep = ordered[:max(1, limit)]
    suppressed = ordered[max(1, limit):]
    return keep, suppressed


def should_block_signal(symbol: str, stage: str, payload: Dict[str, Any]) -> bool:
    direction = str(payload.get("direction", "SHORT")).upper()
    mem_symbol = f"{direction}:{symbol}"
    if stage == "SIGNAL" and daily_trade_already_sent(symbol, direction):
        return True

    now_ts = time.time()
    sig_rec = get_signal_record(mem_symbol, stage)
    sig_ts = safe_float(sig_rec.get("ts", 0))
    if sig_ts and now_ts - sig_ts < ALERT_COOLDOWN_MIN * 60:
        if better_than_previous(mem_symbol, stage, payload):
            stats["cooldown_override"] += 1
            return False
        return True

    setup_rec = memory.get("signals", {}).get(f"setup:{mem_symbol}", {})
    setup_ts = safe_float(setup_rec.get("ts", 0))
    if setup_ts and time.time() - setup_ts < SETUP_COOLDOWN_MIN * 60:
        if better_than_previous(mem_symbol, stage, payload):
            stats["cooldown_override"] += 1
            return False
        return True

    return False


def set_signal_memory(symbol: str, stage: str, payload: Dict[str, Any]) -> None:
    direction = str(payload.get("direction", "SHORT")).upper()
    mem_symbol = f"{direction}:{symbol}"
    memory.setdefault("signals", {})[signal_key(mem_symbol, stage)] = {
        "ts": time.time(),
        "stage": stage,
        "direction": direction,
        "price": payload.get("price"),
        "score": payload.get("score"),
    }
    memory.setdefault("signals", {})[f"setup:{mem_symbol}"] = {
        "ts": time.time(),
        "stage": stage,
        "direction": direction,
        "price": payload.get("price"),
        "score": payload.get("score"),
    }
    if stage == "SIGNAL":
        set_daily_trade_sent(symbol, payload)
    memory["last_signal_ts"] = time.time()


def update_hot_memory(res: Dict[str, Any]) -> None:
    # Deep copy ile orijinal dict'i koru
    res = copy.deepcopy(res)
    sym = res["symbol"]
    hot = memory.setdefault("hot", {})
    rec = hot.get(sym, {})
    old_price = safe_float(rec.get("first_price", 0))
    if old_price <= 0:
        old_price = safe_float(res.get("price", 0))
    hot[sym] = {
        "first_seen": rec.get("first_seen", time.time()),
        "last_seen": time.time(),
        "first_price": old_price,
        "last_price": res.get("price"),
        "score": max(safe_float(rec.get("score", 0)), safe_float(res.get("score", 0))),
        "invisible_score": safe_float(res.get("invisible_score", rec.get("invisible_score", 0))),
        "invisible_class": res.get("invisible_class", rec.get("invisible_class", "-")),
        "invisible_decision": res.get("invisible_decision", rec.get("invisible_decision", "-")),
        "invisible_summary": {
            "av_nerede": (res.get("invisible_face") or {}).get("av_nerede", (rec.get("invisible_summary") or {}).get("av_nerede", "-")),
            "likidite_nerede": (res.get("invisible_face") or {}).get("likidite_nerede", (rec.get("invisible_summary") or {}).get("likidite_nerede", "-")),
            "islem_alinabilir_mi": (res.get("invisible_face") or {}).get("islem_alinabilir_mi", (rec.get("invisible_summary") or {}).get("islem_alinabilir_mi", "-")),
            "supurme_hedefi": (res.get("invisible_face") or {}).get("supurme_hedefi", (rec.get("invisible_summary") or {}).get("supurme_hedefi", "-")),
        },
        "reason": res.get("reason", ""),
        "updates": int(safe_float(rec.get("updates", 0))) + 1,
        "last_rise_notice_ts": safe_float(rec.get("last_rise_notice_ts", 0)),
    }


# =========================================================
# MESAJ FORMATLARI
# =========================================================
def fmt_num(v: float) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "0.0000"
    if abs(v) >= 1000:
        # Binler ayracı ile Türkçe format: 1.234,5678
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


def build_signal_message(res: Dict[str, Any]) -> str:
    if str(res.get("direction", "SHORT")).upper() == "LONG":
        return build_long_signal_message(res)
    confirm_status = str(res.get("binance_confirm_status", "YOK"))
    binance_symbol = str(res.get("binance_symbol", "-"))
    binance_price = safe_float(res.get("binance_price", 0))
    binance_gap = safe_float(res.get("binance_price_gap_pct", 0))
    binance_reason = str(res.get("binance_confirm_reason", "-"))
    data_engine = str(res.get("data_engine", "OKX SWAP"))
    signal_label = "SHORT AL"
    base = (
        f"🚨 {VERSION_NAME} - {signal_label}\n"
        f"Saat: {tr_str()}\n"
        f"Coin: {res['symbol']}\n"
        f"Veri motoru: {data_engine}\n"
        f"Binance teyit: {confirm_status}\n"
        f"Binance sembol: {binance_symbol}\n"
        f"Skor: {res['score']}\n"
        f"Kalite skoru: {res.get('quality_score', '-')}\n"
        f"Aday/Hazır/Doğrula: {res['candidate_score']} / {res['ready_score']} / {res['verify_score']}\n"
        f"Trend kilit skoru: {res.get('trend_guard_score', '-')}\n"
        f"Kırılım skoru: {res.get('breakdown_score', '-')}\n"
        f"Görünmeyen yüz: {res.get('invisible_class', '-')} / {res.get('invisible_score', '-')}\n"
        f"5m/15m kapanış: {res.get('close_confirm_gate', {}).get('class', '-')} | 5m={res.get('close_confirm_gate', {}).get('score5', '-')} | 15m={res.get('close_confirm_gate', {}).get('score15', '-')}\n"
        f"Tepe erken modu: {'AKTİF' if res.get('top_early_short') else '-'} | çıkış skoru={res.get('top_exit_score', '-')} | tepe yaşı={res.get('peak_age_candles', '-')} mum\n"
        f"OKX fiyat: {fmt_num(res['price'])}\n"
        f"Binance fiyat: {fmt_num(binance_price) if binance_price > 0 else '-'}\n"
        f"OKX-Binance farkı: %{binance_gap:.2f}\n"
        f"Entry: {fmt_num(res['price'])}\n"
        f"Stop: {fmt_num(res['stop'])}\n"
        f"TP1: {fmt_num(res['tp1'])}\n"
        f"TP2: {fmt_num(res['tp2'])}\n"
        f"TP3: {fmt_num(res['tp3'])}\n"
        f"RR(TP1): {res['rr']}\n"
        f"10dk/20dk/1s Pump: %{res['pump_10m']} / %{res['pump_20m']} / %{res['pump_1h']}\n"
        f"RSI 1/5/15: {res['rsi1']} / {res['rsi5']} / {res['rsi15']}\n"
        f"Hacim 1/5: x{res['vol_ratio_1m']} / x{res['vol_ratio_5m']}\n"
        f"Not: {res['reason']}\n"
        f"Kalite notu: {res.get('quality_reason', '-')}\n"
        f"Binance notu: {binance_reason}"
    )
    return base + format_invisible_face_block(res) + format_ict_block(res)





def format_ict_block(res: Dict[str, Any]) -> str:
    ict = res.get("ict") if isinstance(res.get("ict"), dict) else {}
    if not ict or not ict.get("enabled"):
        return ""
    flow = res.get("trade_flow") if isinstance(res.get("trade_flow"), dict) else {}
    book = res.get("orderbook") if isinstance(res.get("orderbook"), dict) else {}
    bull_ob = ict.get("bullish_ob", {}) if isinstance(ict.get("bullish_ob"), dict) else {}
    bear_ob = ict.get("bearish_ob", {}) if isinstance(ict.get("bearish_ob"), dict) else {}
    bull_fvg = ict.get("nearest_bullish_fvg", {}) if isinstance(ict.get("nearest_bullish_fvg"), dict) else {}
    bear_fvg = ict.get("nearest_bearish_fvg", {}) if isinstance(ict.get("nearest_bearish_fvg"), dict) else {}
    return (
        "\n\n🏛️ ICT PRO BÖLGE / YAPI MOTORU\n"
        f"📏 Swing: {fmt_num(ict.get('swing_low', 0))} → {fmt_num(ict.get('swing_high', 0))} | Aralık %{ict.get('range_pct', 0)}\n"
        f"⚖️ EQ / 0.5: {fmt_num(ict.get('equilibrium', 0))}\n"
        f"🟢 Discount 0.5-0.618: {fmt_num(ict.get('discount_low', 0))} - {fmt_num(ict.get('discount_high', 0))} | içinde mi: {'EVET' if ict.get('in_discount_zone') else 'HAYIR'}\n"
        f"🔴 Premium: {fmt_num(ict.get('premium_low', 0))} - {fmt_num(ict.get('premium_high', 0))} | içinde mi: {'EVET' if ict.get('in_premium_zone') else 'HAYIR'}\n"
        f"🧭 Market structure: {ict.get('structure_bias', '-')} | BOS↑ {ict.get('bos_up')} / BOS↓ {ict.get('bos_down')} | CHOCH↑ {ict.get('choch_up')} / CHOCH↓ {ict.get('choch_down')} | MSS↑ {ict.get('mss_up')} / MSS↓ {ict.get('mss_down')}\n"
        f"💧 Likidite: BSL {fmt_num(ict.get('buy_side_liquidity', 0))} | SSL {fmt_num(ict.get('sell_side_liquidity', 0))} | equal high/low: {ict.get('equal_high')}/{ict.get('equal_low')} | sweep alt/üst: {ict.get('sweep_low')}/{ict.get('sweep_high')}\n"
        f"🧱 Order Block: bullish {fmt_num(bull_ob.get('low', 0))}-{fmt_num(bull_ob.get('high', 0))} yakın={ict.get('bullish_ob_near')} | bearish {fmt_num(bear_ob.get('low', 0))}-{fmt_num(bear_ob.get('high', 0))} yakın={ict.get('bearish_ob_near')}\n"
        f"🕳️ FVG: bullish {fmt_num(bull_fvg.get('low', 0))}-{fmt_num(bull_fvg.get('high', 0))} aktif={ict.get('bullish_fvg_active')} | bearish {fmt_num(bear_fvg.get('low', 0))}-{fmt_num(bear_fvg.get('high', 0))} aktif={ict.get('bearish_fvg_active')}\n"
        f"🔁 CHOCH/BOS skoru: yukarı {ict.get('choch_up_score', 0)} ({ict.get('choch_up_reason', '-')}) | aşağı {ict.get('choch_down_score', 0)} ({ict.get('choch_down_reason', '-')})\n"
        f"🎯 ICT PRO skor: SHORT {ict.get('short_pro_score', 0)} ({ict.get('short_pro_reason', '-')}) | LONG {ict.get('long_pro_score', 0)} ({ict.get('long_pro_reason', '-')})\n"
        f"🕰️ Kill zone: {'EVET' if ict.get('killzone_active') else 'hayır'} | {ict.get('killzone_name', '-')}\n"
        f"🧲 Orderbook: {book.get('reason', 'OKX orderbook') if book else '-'} | baskı {book.get('book_pressure', '-') if book else '-'}\n"
        f"⚔️ Trade flow: alış/satış x{flow.get('buy_to_sell', '-')} | satış/alış x{flow.get('sell_to_buy', '-')}\n"
        f"📌 ICT notu: {ict.get('reason', '-') }"
    )

def build_long_signal_message(res: Dict[str, Any]) -> str:
    confirm_status = str(res.get("binance_confirm_status", "YOK"))
    binance_symbol = str(res.get("binance_symbol", "-"))
    binance_price = safe_float(res.get("binance_price", 0))
    binance_gap = safe_float(res.get("binance_price_gap_pct", 0))
    binance_reason = str(res.get("binance_confirm_reason", "-"))
    data_engine = str(res.get("data_engine", "OKX SWAP"))
    gate = res.get("long_close_gate", {}) if isinstance(res.get("long_close_gate"), dict) else {}
    base = (
        f"🚀 {VERSION_NAME} - LONG AL\n"
        f"Saat: {tr_str()}\n"
        f"Coin: {res['symbol']}\n"
        f"Veri motoru: {data_engine}\n"
        f"Binance teyit: {confirm_status}\n"
        f"Binance sembol: {binance_symbol}\n"
        f"Skor: {res['score']}\n"
        f"Kalite skoru: {res.get('quality_score', '-')}\n"
        f"Aday/Hazır/Doğrula: {res['candidate_score']} / {res['ready_score']} / {res['verify_score']}\n"
        f"LONG yapı skoru: {res.get('long_structure_score', res.get('breakdown_score', '-'))}\n"
        f"ICT sınıfı: {res.get('invisible_class', '-')} / {res.get('invisible_score', '-')}\n"
        f"5m/15m kapanış: {gate.get('class', '-')} | 5m={gate.get('score5', '-')} | 15m={gate.get('score15', '-')}\n"
        f"OKX fiyat: {fmt_num(res['price'])}\n"
        f"Binance fiyat: {fmt_num(binance_price) if binance_price > 0 else '-'}\n"
        f"OKX-Binance farkı: %{binance_gap:.2f}\n"
        f"Entry: {fmt_num(res['price'])}\n"
        f"Stop: {fmt_num(res['stop'])}\n"
        f"TP1: {fmt_num(res['tp1'])}\n"
        f"TP2: {fmt_num(res['tp2'])}\n"
        f"TP3: {fmt_num(res['tp3'])}\n"
        f"RR(TP1): {res['rr']}\n"
        f"10dk/20dk/1s Düşüş/Pullback: %{res.get('drop_10m', 0)} / %{res.get('drop_20m', 0)} / %{res.get('drop_1h', 0)}\n"
        f"RSI 1/5/15: {res['rsi1']} / {res['rsi5']} / {res['rsi15']}\n"
        f"Hacim 1/5: x{res['vol_ratio_1m']} / x{res['vol_ratio_5m']}\n"
        f"Not: {res['reason']}\n"
        f"Kalite notu: {res.get('quality_reason', '-')}\n"
        f"Binance notu: {binance_reason}"
    )
    return base + format_ict_block(res)

def build_hot_message(res: Dict[str, Any]) -> str:
    base = (
        f"🔥 SICAK TAKİP\n"
        f"Saat: {tr_str()}\n"
        f"Coin: {res['symbol']}\n"
        f"Skor: {res['score']}\n"
        f"Fiyat: {fmt_num(res['price'])}\n"
        f"Trend kilit skoru: {res.get('trend_guard_score', '-')}\n"
        f"Kırılım skoru: {res.get('breakdown_score', '-')}\n"
        f"Görünmeyen yüz: {res.get('invisible_class', '-')} / {res.get('invisible_score', '-')}\n"
        f"Durum: Şimdilik net short AL değil, sıcak takibe alındı. Yükseliş bozulmadan short yok.\n"
        f"Not: {res['reason']}"
    )
    return base + format_invisible_face_block(res)


def build_ready_message(res: Dict[str, Any]) -> str:
    base = (
        f"🟠 İNCE TAKİP\n"
        f"Saat: {tr_str()}\n"
        f"Coin: {res['symbol']}\n"
        f"Skor: {res['score']}\n"
        f"Fiyat: {fmt_num(res['price'])}\n"
        f"Trend kilit skoru: {res.get('trend_guard_score', '-')}\n"
        f"Kırılım skoru: {res.get('breakdown_score', '-')}\n"
        f"Görünmeyen yüz: {res.get('invisible_class', '-')} / {res.get('invisible_score', '-')}\n"
        f"Kalite: {res.get('quality_score', '-')}\n"
        f"Not: Zemin oluşuyor ama gerçek kalite kapısı bekleniyor. {res['reason']}"
    )
    return base + format_invisible_face_block(res)


def build_heartbeat_message() -> str:
    hot_count = len(memory.get("hot", {}))
    trend_watch_count = len(memory.get("trend_watch", {}))
    last_sig = safe_float(memory.get("last_signal_ts", 0))
    last_sig_txt = tr_str(last_sig) if last_sig else "Yok"
    return (
        f"💓 {VERSION_NAME} DURUM\n"
        f"Saat: {tr_str()}\n"
        f"Toplam coin: {len(COINS)}\n"
        f"Sıcak coin: {hot_count}\n"
        f"Trend izleme: {trend_watch_count}\n"
        f"Bloklu coin: {get_blocked_symbol_count()}\n"
        f"Çıkarılan coin: {stats['okx_symbol_pruned']}\n"
        f"Son sinyal: {last_sig_txt}\n"
        f"Analiz: {stats['analyzed']}\n"
        f"Gönderilen sinyal: {stats['signal_sent']}\n"
        f"Bugün atılan short coin: {get_today_short_sent_count()}/{DAILY_SHORT_TOTAL_LIMIT}\n"
        f"Takibe alınan: {stats['hot_add']}\n"
        f"Trend koruma blok: {stats['trend_guard_block_signal']}\n"
        f"Kırılım geçen: {stats['trend_breakdown_pass']}\n"
        f"Kırılım aday desteği: {stats['breakdown_candidate_assist']}\n"
        f"Görünmeyen yüz clean/scalp/watch/blok: {stats['invisible_face_clean']} / {stats['invisible_face_scalp']} / {stats['invisible_face_watch']} / {stats['invisible_face_block']}\n"
        f"Tepe erken sinyal/geç blok: {stats['tepe_early_signal']} / {stats['tepe_late_block']}\n"
        f"Orderbook/trade okuma: {stats['orderbook_ok']}/{stats['orderbook_fail']} | {stats['trades_ok']}/{stats['trades_fail']}\n"
        f"Kalite kapısı blok: {stats['quality_gate_block']}\n"
        f"5m/15m kapanış blok/riskli: {stats['close_confirm_block']} / {stats['close_confirm_risky']}\n"
        f"PEPE/bloklu coin skip: {stats['blocked_coin_skip']}\n"
        f"RR blok: {stats['rr_block']}\n"
        f"Günlük toplam limit blok: {stats['daily_total_block']}\n"
        f"Cooldown override: {stats['cooldown_override']}\n"
        f"Binance teyit pass/soft/fail: {stats['binance_confirm_pass']} / {stats['binance_confirm_soft']} / {stats['binance_confirm_fail']}\n"
        f"Binance teyit yok: {stats['binance_confirm_unavailable']}\n"
        f"API fail: {stats['api_fail']}\n"
        f"Telegram fail: {stats['telegram_fail']}\n"
        f"Red: weak_candidate={stats['weak_candidate_reject']}, weak_signal={stats['weak_signal_reject']}, cooldown={stats['cooldown_reject']}, daily_short={stats['daily_short_block']}, invalid={stats['invalid_symbol_skip']}, blocked={stats['blocked_symbol_skip']}"
    )


def build_diagnostic_message() -> str:
    hot_count = len(memory.get("hot", {}))
    trend_watch_count = len(memory.get("trend_watch", {}))
    last_sig = safe_float(memory.get("last_signal_ts", 0))
    no_sig_min = int((time.time() - last_sig) / 60) if last_sig else -1
    return (
        f"🛠 SİNYAL TEŞHİS RAPORU\n"
        f"Saat: {tr_str()}\n"
        f"Son AL üzerinden geçen süre: {no_sig_min if no_sig_min >= 0 else 'Hiç yok'} dk\n"
        f"Sıcak coin sayısı: {hot_count}\n"
        f"Trend izleme: {trend_watch_count}\n"
        f"Analiz: {stats['analyzed']}\n"
        f"Zayıf aday red: {stats['weak_candidate_reject']}\n"
        f"Hazır ama final değil: {stats['weak_signal_reject']}\n"
        f"Trend koruma blok: {stats['trend_guard_block_signal']}\n"
        f"Kırılım geçen: {stats['trend_breakdown_pass']}\n"
        f"Kalite kapısı blok: {stats['quality_gate_block']}\n"
        f"Görünmeyen yüz blok/promote: {stats['invisible_face_block']} / {stats['invisible_face_promote']}\n"
        f"RR blok: {stats['rr_block']}\n"
        f"Binance teyit fail: {stats['binance_confirm_fail']}\n"
        f"Binance teyit yok: {stats['binance_confirm_unavailable']}\n"
        f"Yorum: V5.2.7.1 toplu AL basmaz; fırsat varsa gün içine yayar, yoksa kota doldurmaz."
    )


# =========================================================
# SİNYAL İŞLEME
# =========================================================
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

        if res.get("stage") != "SIGNAL" or str(res.get("signal_label", "")) != expected_label:
            logger.info("%s sinyali susturdu %s: %s", expected_label, symbol, res.get("reason", "-"))
            update_hot_memory(copy.deepcopy(res))
            return
        logger.info("%s ÜRETİLDİ %s skor=%s kalite=%s", expected_label, symbol, res.get("score"), res.get("quality_score"))

        if daily_trade_already_sent(symbol, direction):
            stats["daily_short_block"] += 1
            logger.info("GÜNLÜK %s KİLİDİ %s", direction, symbol)
            update_hot_memory({**copy.deepcopy(res), "stage": "READY", "reason": f"{res.get('reason', '')} | Aynı coin bugün zaten {expected_label} aldı, sessiz takip."})
            return

        if get_today_trade_sent_count(direction) >= get_daily_trade_limit(direction):
            stats["daily_total_block"] += 1
            logger.info("GÜNLÜK TOPLAM %s LİMİTİ DOLDU %s", direction, symbol)
            update_hot_memory({**copy.deepcopy(res), "stage": "READY", "reason": f"{res.get('reason', '')} | Günlük {direction} üst sınırı doldu, kota doldurma yok."})
            return

        if has_active_trade():
            stats["active_trade_block"] += 1
            logger.info("AKTİF İŞLEM MODU BLOK %s", symbol)
            update_hot_memory({**copy.deepcopy(res), "stage": "READY", "reason": f"{res.get('reason', '')} | Aktif işlem varken yeni AL basılmadı, sessiz takip."})
            return

        if global_signal_gap_active():
            stats["global_gap_block"] += 1
            logger.info("SİNYAL ARALIĞI BLOK %s", symbol)
            update_hot_memory({**copy.deepcopy(res), "stage": "READY", "reason": f"{res.get('reason', '')} | Son AL çok yakın, toplu sinyal engeli."})
            return

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
                gy_okx_override = (
                    GORUNMEYEN_YUZ_BINANCE_FAIL_OVERRIDE
                    and confirm_status != "HARD_FAIL"
                    and str(res.get("invisible_decision", "")) in ("SHORT_AL_SERBEST", "TP1_SCALP_SERBEST", "TEPE_PARA_CIKISI_SERBEST")
                    and safe_float(res.get("invisible_score", 0)) >= GORUNMEYEN_YUZ_MIN_CLEAN_SCORE
                )
                if not gy_okx_override:
                    stats["signal_downgraded_by_binance"] += 1
                    logger.info("BINANCE TEYİDİ RED %s status=%s", symbol, confirm_status)
                    downgraded = copy.deepcopy(res)
                    downgraded["stage"] = "READY"
                    downgraded["reason"] = f"{res.get('reason', '')} | Binance teyidi zayıf: {confirm.get('reason', '-')}"
                    update_hot_memory(downgraded)
                    return
                res["binance_confirm_reason"] = f"{confirm.get('reason', '-')} | OKX görünmeyen yüz güçlü olduğu için Binance soft tutuldu."
            elif confirm_status == "UNAVAILABLE":
                stats["binance_confirm_unavailable"] += 1
                gy_unavailable_override = (
                    not BINANCE_CONFIRM_REQUIRED
                    and str(res.get("invisible_decision", "")) in ("SHORT_AL_SERBEST", "TP1_SCALP_SERBEST", "TEPE_PARA_CIKISI_SERBEST")
                    and safe_float(res.get("invisible_score", 0)) >= GORUNMEYEN_YUZ_MIN_SCALP_SCORE
                )
                if (
                    BINANCE_CONFIRM_REQUIRED
                    or (
                        not gy_unavailable_override
                        and (
                            safe_float(res.get("score", 0)) < BINANCE_CONFIRM_FAIL_OPEN_SCORE
                            or safe_float(res.get("breakdown_score", 0)) < BREAKDOWN_ASSIST_STRONG_SCORE
                        )
                    )
                ):
                    stats["signal_downgraded_by_binance"] += 1
                    logger.info("BINANCE TEYİDİ YOK, SİNYAL DÜŞÜRÜLDÜ %s", symbol)
                    downgraded = copy.deepcopy(res)
                    downgraded["stage"] = "READY"
                    downgraded["reason"] = f"{res.get('reason', '')} | Binance teyidi yok, takipte tutuldu."
                    update_hot_memory(downgraded)
                    return
                if gy_unavailable_override:
                    res["binance_confirm_reason"] = f"{confirm.get('reason', '-')} | OKX görünmeyen yüz motoru izin verdi."
            elif confirm_status == "DISABLED":
                pass
        else:
            # LONG motoru ayrı çalışır. Binance short teyit motoru burada kullanılmaz.
            res["data_engine"] = "OKX SWAP + ICT LONG"
            res["binance_confirm_status"] = "NOT_USED"
            res["binance_confirm_score"] = 0
            res["binance_symbol"] = normalize_binance_symbol(symbol)
            res["binance_price"] = 0
            res["binance_price_gap_pct"] = 0
            res["binance_confirm_reason"] = "LONG motoru ayrı ICT/OKX teyidiyle çalışır; short Binance teyidi kullanılmadı."

        if should_block_signal(symbol, "SIGNAL", res):
            stats["cooldown_reject"] += 1
            logger.info("COOLDOWN RED %s %s skor=%s", direction, symbol, res.get("score"))
            update_hot_memory({**copy.deepcopy(res), "stage": "READY", "reason": f"{res.get('reason', '')} | Cooldown nedeniyle sessiz takip."})
            return

        ok = await safe_send_telegram(build_signal_message(res))
        if ok:
            logger.info("TELEGRAM GÖNDERİLDİ %s %s", expected_label, symbol)
            stats["signal_sent"] += 1
            if direction == "LONG":
                stats["long_signal_sent"] += 1
            set_signal_memory(symbol, "SIGNAL", res)
            follow_key = f"{direction}:{symbol}"
            memory.setdefault("follows", {})[follow_key] = {
                "created_ts": time.time(),
                "symbol": symbol,
                "direction": direction,
                "entry": res["price"],
                "stop": res["stop"],
                "tp1": res["tp1"],
                "tp2": res["tp2"],
                "tp3": res["tp3"],
                "stage": "SIGNAL",
                "done": False,
                "sent_ts": time.time(),
            }
            memory.get("hot", {}).pop(symbol, None)
            memory.get("trend_watch", {}).pop(symbol, None)
        else:
            logger.warning("TELEGRAM GÖNDERİLEMEDİ %s %s", expected_label, symbol)
        return

    if stage in ("READY", "HOT"):
        logger.info("TAKİP AŞAMASI %s %s stage=%s skor=%s", direction, symbol, stage, res.get("score"))
        update_hot_memory(res)
        return


async def maybe_send_hot_rise_updates() -> None:
    if not AUTO_HOT_RISE_UPDATE:
        return
    hot = memory.get("hot", {})
    if not hot:
        return
    tickers24 = await get_24h_tickers()
    now_ts = time.time()
    for sym, rec in list(hot.items()):
        first_price = safe_float(rec.get("first_price", 0))
        last_notice = safe_float(rec.get("last_rise_notice_ts", 0))
        t = tickers24.get(sym, {})
        cur = safe_float(t.get("last", 0))
        if first_price <= 0 or cur <= 0:
            continue
        rise_pct = pct_change(first_price, cur)
        if rise_pct >= 1.2 and (now_ts - last_notice > 1800):
            text = (
                f"📈 SICAK COIN GÜNCELLEME\n"
                f"Saat: {tr_str()}\n"
                f"Coin: {sym}\n"
                f"İlk fiyat: {fmt_num(first_price)}\n"
                f"Güncel fiyat: {fmt_num(cur)}\n"
                f"Hareket: %{rise_pct:.2f}\n"
                f"Not: Coin sıcak izleniyordu, yukarı devam etti. Short için kör atlama yok; kırılım teyidi aranıyor."
            )
            ok = await safe_send_telegram(text)
            if ok:
                rec["last_rise_notice_ts"] = now_ts


async def check_followups() -> None:
    follows = memory.get("follows", {})
    if not follows:
        return
    tickers24 = await get_24h_tickers()
    now_ts = time.time()
    for key, rec in list(follows.items()):
        if rec.get("done"):
            continue
        sent_ts = safe_float(rec.get("sent_ts", 0))
        if now_ts - sent_ts < FOLLOWUP_DELAY_SEC:
            continue
        sym = str(rec.get("symbol", key)).replace("LONG:", "").replace("SHORT:", "")
        direction = str(rec.get("direction", "SHORT")).upper()
        t = tickers24.get(sym, {})
        cur = safe_float(t.get("last", 0))
        if cur <= 0:
            continue
        entry = safe_float(rec.get("entry", 0))
        stop = safe_float(rec.get("stop", 0))
        tp1 = safe_float(rec.get("tp1", 0))
        outcome = "NÖTR"
        if direction == "LONG":
            pnl_pct = pct_change(entry, cur)
            if cur <= stop:
                outcome = "STOP"
            elif cur >= tp1:
                outcome = "KÂRDA"
            direction_text = "Long yön tahmini değişim"
        else:
            pnl_pct = pct_change(entry, cur) * -1
            if cur >= stop:
                outcome = "STOP"
            elif cur <= tp1:
                outcome = "KÂRDA"
            direction_text = "Kısa yön tahmini değişim"
        text = (
            f"⏱ 2 SAAT SONRA TAKİP\n"
            f"Saat: {tr_str()}\n"
            f"Yön: {direction}\n"
            f"Coin: {sym}\n"
            f"Entry: {fmt_num(entry)}\n"
            f"Güncel: {fmt_num(cur)}\n"
            f"Sonuç: {outcome}\n"
            f"{direction_text}: %{pnl_pct:.2f}"
        )
        ok = await safe_send_telegram(text)
        if ok:
            stats["followup_sent"] += 1
            rec["done"] = True


# =========================================================
# TARAMA DÖNGÜLERİ
# =========================================================
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
    """SHORT ve LONG motorlarını ayrı ayrı çalıştırır. Çakışma varsa ikisini de dış sinyal yapmaz."""
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
            r["reason"] = f"{r.get('reason', '')} | LONG/SHORT motorları çakıştı; işlem yok."
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
                    direction = str(res.get("direction", "SHORT")).upper()
                    if res["stage"] == "SIGNAL":
                        logger.info("HOT LOOP ADAY %s %s stage=%s skor=%s", direction, sym, res["stage"], res.get("score"))
                        signal_candidates.append(res)
                    elif res["stage"] in ("READY", "HOT"):
                        logger.info("HOT LOOP TAKİP %s %s stage=%s skor=%s", direction, sym, res["stage"], res.get("score"))
                        update_hot_memory(res)
                    else:
                        stats["rejected"] += 1

            chosen, suppressed = select_best_signals(signal_candidates, MAX_SIGNAL_PER_SCAN)
            for res in suppressed:
                stats["scan_signal_suppressed"] += 1
                update_hot_memory({**copy.deepcopy(res), "stage": "READY", "reason": f"{res.get('reason', '')} | Aynı taramada daha güçlü aday seçildi, bu coin sessiz takipte."})
            for res in chosen:
                await maybe_send_signal(res)

            await maybe_send_hot_rise_updates()
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
                    direction = str(res.get("direction", "SHORT")).upper()
                    if res["stage"] == "SIGNAL":
                        logger.info("DEEP LOOP ADAY %s %s stage=%s skor=%s", direction, sym, res["stage"], res.get("score"))
                        signal_candidates.append(res)
                    elif res["stage"] in ("HOT", "READY"):
                        logger.info("DEEP LOOP TAKİP %s %s stage=%s skor=%s", direction, sym, res["stage"], res.get("score"))
                        update_hot_memory(res)
                    else:
                        stats["rejected"] += 1

            chosen, suppressed = select_best_signals(signal_candidates, MAX_SIGNAL_PER_SCAN)
            for res in suppressed:
                stats["scan_signal_suppressed"] += 1
                update_hot_memory({**copy.deepcopy(res), "stage": "READY", "reason": f"{res.get('reason', '')} | Aynı taramada daha güçlü aday seçildi, bu coin sessiz takipte."})
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


async def diagnostic_loop() -> None:
    while True:
        try:
            last_sig = safe_float(memory.get("last_signal_ts", 0))
            last_diag = safe_float(memory.get("last_diag_ts", 0))
            now_ts = time.time()
            if (last_sig == 0 or now_ts - last_sig >= NO_SIGNAL_DIAG_SEC) and (now_ts - last_diag >= NO_SIGNAL_DIAG_SEC):
                ok = await safe_send_telegram(build_diagnostic_message())
                if ok:
                    memory["last_diag_ts"] = now_ts
        except Exception as e:
            logger.exception("diagnostic_loop hata: %s", e)
        await asyncio.sleep(600)


async def followup_loop() -> None:
    while True:
        try:
            await check_followups()
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
        f"{VERSION_NAME} aktif.\n"
        "Komutlar:\n"
        "/status - durum\n"
        "/test - test mesajı\n"
        "/scan - kısa özet tarama\n"
        "/coin BTCUSDT - tek coin analiz\n"
        "/hot - sıcak coinler\n"
        "/trend - trend izleme listesi\n"
        "/av - görünmeyen yüz av listesi\n"
        "Not: Görünmeyen yüz motoru av/likidite/tuzak/dağıtım kapısıdır. EMA/RSI karar değil, sadece teyittir."
    )


async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ok = await safe_send_telegram(f"✅ Test mesajı başarılı. Saat: {tr_str()}")
    await update.message.reply_text("Test mesajı gönderildi." if ok else "Test mesajı gönderilemedi.")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(build_heartbeat_message())


async def cmd_hot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    hot = memory.get("hot", {})
    if not hot:
        await update.message.reply_text("Şu an sıcak coin yok.")
        return
    items = sorted(hot.items(), key=lambda x: safe_float(x[1].get("score", 0)), reverse=True)[:10]
    lines = ["🔥 Sıcak coinler:"]
    for sym, rec in items:
        lines.append(
            f"- {sym} | skor={safe_float(rec.get('score', 0)):.1f} | ilk={fmt_num(safe_float(rec.get('first_price', 0)))} | son={fmt_num(safe_float(rec.get('last_price', 0)))}"
        )
    await update.message.reply_text("\n".join(lines))


async def cmd_trend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    trend_watch = memory.get("trend_watch", {})
    if not trend_watch:
        await update.message.reply_text("Şu an trend devam kilidine takılan coin yok.")
        return
    items = sorted(trend_watch.items(), key=lambda x: safe_float(x[1].get("score", 0)), reverse=True)[:12]
    lines = ["🧲 Trend izleme / short erken kilidi:"]
    for sym, rec in items:
        first_price = safe_float(rec.get("first_price", 0))
        last_price = safe_float(rec.get("last_price", 0))
        move = pct_change(first_price, last_price) if first_price > 0 and last_price > 0 else 0.0
        lines.append(
            f"- {sym} | skor={safe_float(rec.get('score', 0)):.1f} | ilk={fmt_num(first_price)} | son={fmt_num(last_price)} | hareket=%{move:.2f} | kırılım={safe_float(rec.get('breakdown_score', 0)):.1f}"
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
        await update.message.reply_text("🎯 Şu an görünmeyen yüz av listesinde coin yok.")
        return

    items = sorted(
        merged.items(),
        key=lambda x: (
            safe_float(x[1].get("invisible_score", 0)),
            safe_float(x[1].get("score", 0))
        ),
        reverse=True
    )[:15]

    lines = ["🎯 AV LİSTESİ / GÖRÜNMEYEN YÜZ"]
    for sym, rec in items:
        first_price = safe_float(rec.get("first_price", 0))
        last_price = safe_float(rec.get("last_price", 0))
        move = pct_change(first_price, last_price) if first_price > 0 and last_price > 0 else 0.0
        summary = rec.get("invisible_summary", {}) or {}
        lines.append(
            f"- {sym} | {rec.get('invisible_class', '-')} | GY={safe_float(rec.get('invisible_score', 0)):.1f} | "
            f"ilk={fmt_num(first_price)} son={fmt_num(last_price)} hareket=%{move:.2f}\n"
            f"  Av: {summary.get('av_nerede', '-')}\n"
            f"  Likidite: {summary.get('likidite_nerede', '-')}\n"
            f"  Alınabilirlik: {summary.get('islem_alinabilir_mi', '-')}"
        )

    await update.message.reply_text("\n".join(lines[:46]))


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tickers24 = await get_24h_tickers()
    syms = pick_general_symbols(8)
    out = ["🔎 Hızlı tarama:"]
    for sym in syms:
        res = await analyze_symbol(sym, tickers24)
        if not res:
            continue
        out.append(
            f"- {sym} | {res['stage']} | skor={res.get('score', 0)} | GY={res.get('invisible_class', '-')}/{res.get('invisible_score', '-')} | fiyat={fmt_num(safe_float(res.get('price', 0)))} | kırılım={res.get('breakdown_score', '-')}"
        )
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
        res["binance_symbol"] = confirm.get("binance_symbol", normalize_binance_symbol(symbol))
        res["binance_price"] = confirm.get("binance_price", 0)
        res["binance_price_gap_pct"] = confirm.get("price_gap_pct", 0)
        res["binance_confirm_reason"] = confirm.get("reason", "-")
        await update.message.reply_text(build_signal_message(res))
    elif res["stage"] == "READY":
        await update.message.reply_text(build_ready_message(res))
    elif res["stage"] == "HOT":
        await update.message.reply_text(build_hot_message(res))
    else:
        base = (
            f"{symbol} şu an short için zayıf.\n"
            f"Skor: {res.get('score', 0)}\n"
            f"Kalite: {res.get('quality_score', 0)}\n"
            f"Görünmeyen yüz: {res.get('invisible_class', '-')} / {res.get('invisible_score', '-')}\n"
            f"Trend kilit skoru: {res.get('trend_guard_score', '-')}\n"
            f"Kırılım skoru: {res.get('breakdown_score', '-')}\n"
            f"Sebep: {res.get('reason', 'Yok')}"
        )
        await update.message.reply_text(base + format_invisible_face_block(res))


# =========================================================
# BAŞLATMA
# =========================================================
async def post_init(application) -> None:
    active_count, pruned_count = await refresh_coin_pool(force=True)

    if AUTO_START_MESSAGE:
        await safe_send_telegram(
            f"🚀 {VERSION_NAME} başladı\n"
            f"Saat: {tr_str()}\n"
            f"Coin sayısı: {active_count}\n"
            f"Çıkarılan coin: {pruned_count}\n"
            f"Veri kaynağı: OKX {OKX_INST_TYPE}\n"
            f"Motorlar: sıcak takip + derin analiz + teşhis + heartbeat + symbol refresh + trend devam koruması + kalite kapısı + görünmeyen yüz/likidite avı\n"
            f"Günlük toplam short limiti: {DAILY_SHORT_TOTAL_LIMIT}\n"
            f"Aynı coin günlük short kilidi: açık\n"
            f"Yeni kural: av/likidite/tuzak/dağıtım motoru izin vermeden SHORT AL yok. EMA/RSI sadece teyit."
        )

    asyncio.create_task(hot_scan_loop())
    asyncio.create_task(deep_scan_loop())
    asyncio.create_task(symbol_refresh_loop())
    asyncio.create_task(heartbeat_loop())
    asyncio.create_task(diagnostic_loop())
    asyncio.create_task(followup_loop())
    asyncio.create_task(save_loop())
    logger.info("Arka plan döngüleri başlatıldı")


def validate_config() -> None:
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")
    if missing:
        raise RuntimeError(f"Eksik env: {', '.join(missing)}")


async def shutdown_handler(application) -> None:
    """Bot kapanırken arka plan task'larını düzgün kapat ve memory kaydet."""
    logger.info("Bot kapatılıyor...")
    tasks = application.bot_data.get("tasks", [])
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    save_memory()
    logger.info("Bot güvenli şekilde durduruldu.")

def build_app():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("test", cmd_test))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("health", cmd_status))
    application.add_handler(CommandHandler("scan", cmd_scan))
    application.add_handler(CommandHandler("coin", cmd_coin))
    application.add_handler(CommandHandler("hot", cmd_hot))
    application.add_handler(CommandHandler("trend", cmd_trend))
    application.add_handler(CommandHandler("av", cmd_av))
    # Shutdown handler ekle
    application.post_shutdown = shutdown_handler
    return application


async def shutdown_app(signal_type=None):
    """Graceful shutdown handler - tüm task'ları düzgün kapat."""
    logger.info("Shutdown başlatılıyor... (signal: %s)", signal_type)

    # Önce kendi task'larımızı cancel et
    if app and hasattr(app, 'bot_data') and app.bot_data.get("tasks"):
        tasks = app.bot_data["tasks"]
        for task in tasks:
            if not task.done():
                task.cancel()
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=10.0
            )
        except asyncio.TimeoutError:
            logger.warning("Bazı task'lar zaman aşımına uğradı, zorla kapatılıyor.")

    # Memory kaydet
    save_memory()
    logger.info("Memory kaydedildi.")

    # Uygulamayı durdur
    if app:
        try:
            await app.stop()
            await app.shutdown()
        except Exception as e:
            logger.warning("Uygulama durdurma hatası: %s", e)

    logger.info("Bot güvenli şekilde durduruldu.")


def main() -> None:
    try:
        validate_config()
        load_memory()
        global app
        app = build_app()

        # Signal handler'ları ayarla
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda s=sig: asyncio.create_task(shutdown_app(s.name))
            )

        logger.info("%s polling başlıyor", VERSION_NAME)
        app.run_polling(close_loop=False, drop_pending_updates=True)
    except KeyboardInterrupt:
        logger.info("Kullanıcı tarafından durduruldu.")
    except Exception as e:
        logger.exception("Kritik hata: %s", e)
        raise
    finally:
        # Eğer shutdown_app çalışmadıysa burada da kaydet
        logger.info("Memory kaydediliyor...")
        save_memory()
        logger.info("Bot durdu.")


if __name__ == "__main__":
    main()
