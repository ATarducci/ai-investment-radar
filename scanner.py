#!/usr/bin/env python3
"""Read-only public crypto market scanner; no trading and no forecasts."""
import json, math, statistics, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

SYMBOLS = ['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT','ADAUSDT','DOGEUSDT','AVAXUSDT','LINKUSDT','LTCUSDT','DOTUSDT','TRXUSDT','BCHUSDT','ATOMUSDT','UNIUSDT','ETCUSDT','NEARUSDT','APTUSDT','FILUSDT','ICPUSDT']
ENDPOINTS = ['https://data-api.binance.vision/api/v3/klines','https://api.binance.com/api/v3/klines']
ROOT = Path(__file__).parent

def candles(symbol):
    query = urlencode({'symbol':symbol,'interval':'1h','limit':220})
    last_error = None
    for endpoint in ENDPOINTS:
        try:
            req = urllib.request.Request(endpoint+'?'+query,headers={'User-Agent':'PersonalMarketResearch/1.0'})
            with urllib.request.urlopen(req,timeout=15) as resp:
                rows=json.load(resp)
            if not isinstance(rows,list) or len(rows)<200:
                raise ValueError('Insufficient candles')
            now_ms=datetime.now(timezone.utc).timestamp()*1000
            closed=[x for x in rows if int(x[6])<now_ms]
            if len(closed)<200:
                raise ValueError('Insufficient closed candles')
            return closed,endpoint
        except Exception as exc:
            last_error=exc
    raise RuntimeError(str(last_error))

def ema(values,period):
    v=values[0]
    for x in values[1:]:
        v+= (x-v)*2/(period+1)
    return v

def rsi(values,period=14):
    changes=[values[i]-values[i-1] for i in range(len(values)-period,len(values))]
    gain=sum(max(0,x) for x in changes)/period
    loss=sum(max(0,-x) for x in changes)/period
    return 100 if loss==0 else 100-100/(1+gain/loss)

def analyze(symbol):
    rows,source=candles(symbol)
    close=[float(r[4]) for r in rows]
    volumes=[float(r[5]) for r in rows]
    price=close[-1]
    avg20=ema(close[-80:],20)
    avg50=ema(close[-120:],50)
    rsi14=rsi(close)
    change24=(price/close[-25]-1)*100
    change7=(price/close[-169]-1)*100
    hourly=[math.log(close[i]/close[i-1]) for i in range(len(close)-72,len(close))]
    vol=statistics.stdev(hourly)*math.sqrt(24)*100
    avg_volume=sum(volumes[-25:-1])/24
    volume_ratio=volumes[-1]/avg_volume if avg_volume else None
    score=50+(12 if price>avg20 else -12)+(10 if avg20>avg50 else -10)+(8 if 45<=rsi14<=65 else -8 if rsi14>75 or rsi14<25 else 0)+(6 if change24>0 else -6)
    score=max(0,min(100,score))
    return {'symbol':symbol,'price':round(price,7),'change24h_pct':round(change24,2),'change7d_pct':round(change7,2),'rsi14':round(rsi14,1),'ema20':round(avg20,7),'ema50':round(avg50,7),'volatility24h_pct':round(vol,2),'volume_ratio':round(volume_ratio,2) if volume_ratio is not None else None,'score':score,'status':'Osservare' if score>=65 else 'Neutrale' if score>=40 else 'Debole','last_candle_utc':datetime.fromtimestamp(int(rows[-1][6])/1000,timezone.utc).isoformat(),'source':source,'analysis':'Score euristico non validato; non è una probabilità di profitto.'}

def main():
    results=[]
    errors={}
    for symbol in SYMBOLS:
        try:
            results.append(analyze(symbol))
        except Exception as exc:
            errors[symbol]=str(exc)[:180]
    results.sort(key=lambda x:x['score'],reverse=True)
    path=ROOT/'data'/'latest.json'
    path.parent.mkdir(exist_ok=True)
    output={'generated_at_utc':datetime.now(timezone.utc).isoformat(),'status':'ok' if results else 'unavailable','data_kind':'market indicators, NOT forecast','signals':results,'errors':errors,'disclaimer':'Research only; no investment recommendations or guaranteed returns.'}
    path.write_text(json.dumps(output,indent=2,ensure_ascii=False),encoding='utf-8')
    print('Scanned:',len(results),'Errors:',len(errors))
    if not results:
        raise SystemExit('No market data available')

if __name__=='__main__':
    main()
