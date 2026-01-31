//@version=6
indicator("15m Trend Monitor", overlay=false)

// ============================================================================
// INPUTS
// ============================================================================
ema_fast = input.int(20, "Fast EMA")
ema_slow = input.int(50, "Slow EMA")
rsi_period = input.int(14, "RSI Period")
webhook_secret = input.string("YOUR_SECRET_HERE", "Webhook Secret")

// Thresholds for "significant change"
ema_threshold = input.float(0.0001, "EMA Change Threshold (%)")
rsi_threshold = input.float(0.1, "RSI Change Threshold")

trend_timeframe = "15"

// ============================================================================
// HIGHER TIMEFRAME CALCULATIONS (15m data from 5m chart)
// ============================================================================

// Fetch 15m data using request.security
// CRITICAL: lookahead=off ensures we only get CLOSED candle data
htf_close = request.security(syminfo.tickerid, trend_timeframe, close[1], lookahead=barmerge.lookahead_off)
htf_high = request.security(syminfo.tickerid, trend_timeframe, high[1], lookahead=barmerge.lookahead_off)
htf_low = request.security(syminfo.tickerid, trend_timeframe, low[1], lookahead=barmerge.lookahead_off)
htf_volume = request.security(syminfo.tickerid, trend_timeframe, volume[1], lookahead=barmerge.lookahead_off)
live_price = close

// Calculate indicators on 15m timeframe using CLOSED candles
htf_ema20 = request.security(syminfo.tickerid, trend_timeframe, ta.ema(close, ema_fast)[1], lookahead=barmerge.lookahead_off)
htf_ema50 = request.security(syminfo.tickerid, trend_timeframe, ta.ema(close, ema_slow)[1], lookahead=barmerge.lookahead_off)
htf_rsi = request.security(syminfo.tickerid, trend_timeframe, ta.rsi(close, rsi_period)[1], lookahead=barmerge.lookahead_off)

// VWAP calculation - use current bar for VWAP (it's a cumulative indicator)
htf_vwap = request.security(syminfo.tickerid, trend_timeframe, ta.vwap, lookahead=barmerge.lookahead_off)

// Volume SMA using closed candles
htf_volume_sma = request.security(syminfo.tickerid, trend_timeframe, ta.sma(volume, 20)[1], lookahead=barmerge.lookahead_off)

// Volume ratio
volume_ratio = htf_volume_sma != 0 ? htf_volume / htf_volume_sma : na

// Individual conditions
ema_bullish = htf_ema20 > htf_ema50
rsi_bullish = htf_rsi > 50
vwap_bullish = htf_close > htf_vwap

// Overall trend (2 out of 3 indicators must be bullish)
bullish_count = (ema_bullish ? 1 : 0) + (rsi_bullish ? 1 : 0) + (vwap_bullish ? 1 : 0)
trend_bullish = bullish_count >= 2

// ============================================================================
// CHANGE DETECTION - Track what changed
// ============================================================================

// Store previous indicator values (persistent across bars)
var float prev_ema20 = na
var float prev_ema50 = na
var float prev_rsi = na

// Check if this is first run
bool is_first_bar = na(prev_ema20)

// Check for significant changes in INDICATORS (not price/volume)
bool ema20_changed = is_first_bar or math.abs(htf_ema20 - prev_ema20) > ema_threshold
bool ema50_changed = is_first_bar or math.abs(htf_ema50 - prev_ema50) > ema_threshold
bool rsi_changed = is_first_bar or math.abs(htf_rsi - prev_rsi) > rsi_threshold

// This tells us if INDICATORS changed (not just price/volume/vwap)
bool indicators_changed = ema20_changed or ema50_changed or rsi_changed

// ============================================================================
// ALERT CONDITION - Send EVERY bar, but flag what changed
// ============================================================================

// We ALWAYS send updates (to keep cache fresh and provide volume/price data)
// But we tell Python WHICH data is new vs refreshed

var int update_count = 0
var int significant_count = 0

if barstate.isconfirmed
    update_count := update_count + 1
    if indicators_changed
        significant_count := significant_count + 1
        // Update stored values only when they actually changed
        prev_ema20 := htf_ema20
        prev_ema50 := htf_ema50
        prev_rsi := htf_rsi

// ============================================================================
// ALERT MESSAGE - ALWAYS send, but with metadata
// ============================================================================

if barstate.isconfirmed
    // Parse symbol (remove USDT/USDC/USD suffix)
    baseSymbol = syminfo.ticker
    baseSymbol := str.replace(baseSymbol, "USDT", "")
    baseSymbol := str.replace(baseSymbol, "USDC", "")
    baseSymbol := str.replace(baseSymbol, "USD", "")

    // Build JSON with change flags
    // Python will use these flags to decide what to track
    json_msg = '{\n' + 
         '  "action": "trend_update",\n' + 
         '  "secret": "' + webhook_secret + '",\n' + 
         '  "trends": [{\n' + 
         '    "symbol": "' + baseSymbol + '_USDC",\n' + 
         '    "timeframe": "15",\n' + 
         '    "ema20": ' + str.tostring(htf_ema20, '#.######') + ',\n' + 
         '    "ema50": ' + str.tostring(htf_ema50, '#.######') + ',\n' + 
         '    "rsi": ' + str.tostring(htf_rsi, '#.##') + ',\n' + 
         '    "vwap": ' + str.tostring(htf_vwap, '#.######') + ',\n' + 
         '    "price": ' + str.tostring(live_price, '#.######') + ',\n' +
         '    "volume": ' + str.tostring(htf_volume, '#.####') + ',\n' +
         '    "volume_sma": ' + str.tostring(htf_volume_sma, '#.####') + ',\n' +
         '    "volume_ratio": ' + (na(volume_ratio) ? "null" : str.tostring(volume_ratio, '#.###')) + ',\n' +
         '    "indicators_changed": ' + (indicators_changed ? "true" : "false") + ',\n' +
         '    "change_details": {\n' +
         '      "ema20_changed": ' + (ema20_changed ? "true" : "false") + ',\n' +
         '      "ema50_changed": ' + (ema50_changed ? "true" : "false") + ',\n' +
         '      "rsi_changed": ' + (rsi_changed ? "true" : "false") + '\n' +
         '    }\n' +
         '  }]\n' + 
         '}'
    
    // Always send (to keep cache fresh)
    alert(json_msg, alert.freq_once_per_bar)

// ============================================================================
// PLOTS - For visual confirmation
// ============================================================================
plot(htf_ema20, "15m EMA20", color=color.green, linewidth=2)
plot(htf_ema50, "15m EMA50", color=color.red, linewidth=2)
plot(htf_rsi, "15m RSI", color=color.blue, linewidth=1)
plot(htf_vwap, "15m VWAP", color=color.orange, display=display.none)
plot(htf_close, "15m Price", color=color.white, display=display.none)

// Visual indicator of trend
plot(trend_bullish ? 1 : 0, "Trend", color=trend_bullish ? color.green : color.red, linewidth=3, style=plot.style_histogram)

hline(0.5, "Threshold", color=color.gray, linestyle=hline.style_dashed)
hline(50, "RSI 50", color=color.gray, linestyle=hline.style_dotted)

bgcolor(trend_bullish ? color.new(color.green, 90) : color.new(color.red, 90))
bgcolor(barstate.isconfirmed ? color.new(color.yellow, 95) : na, title="Alert Fired")

// ============================================================================
// INFO TABLE
// ============================================================================
var table info = na
if barstate.islast
    if na(info)
        info := table.new(position.top_right, 2, 12, bgcolor=color.new(color.black, 20), border_width=1)
    
    table.cell(info, 0, 0, "Monitoring:", text_color=color.gray, text_size=size.small)
    table.cell(info, 1, 0, "15m Trend", text_color=color.white, text_size=size.small)
    
    table.cell(info, 0, 1, "Chart TF:", text_color=color.gray, text_size=size.tiny)
    table.cell(info, 1, 1, "2m → 15m data", text_color=color.gray, text_size=size.tiny)
    
    table.cell(info, 0, 2, "Trend:", text_color=color.white)
    table.cell(info, 1, 2, trend_bullish ? "BULLISH ✓" : "BEARISH ✗", text_color=trend_bullish ? color.lime : color.red, text_size=size.large)
    
    table.cell(info, 0, 3, "EMA20>EMA50:", text_color=color.white, text_size=size.small)
    table.cell(info, 1, 3, ema_bullish ? "✓" : "✗", text_color=ema_bullish ? color.lime : color.red, text_size=size.small)
    
    table.cell(info, 0, 4, "RSI>50:", text_color=color.white, text_size=size.small)
    table.cell(info, 1, 4, rsi_bullish ? "✓" : "✗", text_color=rsi_bullish ? color.lime : color.red, text_size=size.small)
    
    table.cell(info, 0, 5, "Price>VWAP:", text_color=color.white, text_size=size.small)
    table.cell(info, 1, 5, vwap_bullish ? "✓" : "✗", text_color=vwap_bullish ? color.lime : color.red, text_size=size.small)
    
    table.cell(info, 0, 6, "Volume:", text_color=color.gray, text_size=size.tiny)
    table.cell(info, 1, 6, na(volume_ratio) ? "N/A" : str.format("{0,number,#.##}x avg", volume_ratio), text_color=color.gray, text_size=size.tiny)
    
    table.cell(info, 0, 7, "EMA Values:", text_color=color.gray, text_size=size.tiny)
    table.cell(info, 1, 7, str.format("{0,number,#.####} / {1,number,#.####}", htf_ema20, htf_ema50), text_color=color.gray, text_size=size.tiny)
    
    table.cell(info, 0, 8, "RSI / Price:", text_color=color.gray, text_size=size.tiny)
    table.cell(info, 1, 8, str.format("{0,number,#.#} / ${1,number,#.####}", htf_rsi, htf_close), text_color=color.gray, text_size=size.tiny)


