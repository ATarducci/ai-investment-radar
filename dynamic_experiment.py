#!/usr/bin/env python3
"""Strategy B: independent forward-only paper trading; never places real orders."""
import json, os, urllib.parse, urllib.request
from pathlib import Path
from datetime import datetime,timezone,timedelta
ROOT=Path(__file__).parent
STATE=ROOT/'data/experiment_dynamic.json'
LATEST=ROOT/'data/latest.json'
FEE=.005
def date(s):return datetime.fromisoformat(s.replace('Z','+00:00'))
def save(s):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def event(s,k,kind,t,msg):
    if any(x['id']==k for x in s['events']):return
    s['events'].append({'id':k,'kind':kind,'time_utc':t,'text':msg,'delivered':False})
    save(s)
def deliver(s):
    token=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
    chat=os.getenv('TELEGRAM_CHAT_ID','').strip()
    for e in s['events']:
        if e.get('delivered'):continue
        if not token or not chat:
            print('B Telegram secrets unavailable; notification pending');return
        try:
            body=urllib.parse.urlencode({'chat_id':chat,'text':e['text']}).encode()
            req=urllib.request.Request('https://api.telegram.org/bot'+token+'/sendMessage',data=body,method='POST')
            with urllib.request.urlopen(req,timeout=20) as response:
                if not json.load(response).get('ok'):raise ValueError('Telegram rejected')
        except Exception as exc:
            print('B Telegram delivery pending:',type(exc).__name__);return
        e['delivered']=True
        save(s)
def sell(p,fraction,price,t,reason):
    fraction=min(fraction,p['remaining_fraction'])
    pnl=p['notional_usdt']*fraction*((price/p['entry_price'])*(1-FEE)**2-1)
    p['remaining_fraction']=round(p['remaining_fraction']-fraction,8)
    p['realized_pnl_usdt']=round(p['realized_pnl_usdt']+pnl,6)
    p['fills'].append({'time_utc':t,'price':price,'fraction_original':fraction,'reason':reason,'net_pnl_usdt':round(pnl,6)})
    if p['remaining_fraction']<1e-7:
        p['remaining_fraction']=0;p['status']='closed';p['closed_at_utc']=t;p['exit_reason']=reason
    return pnl
def main():
    data=json.loads(LATEST.read_text(encoding='utf-8'))
    t=data.get('generated_at_utc')
    if not t or data.get('status')!='ok':raise SystemExit('No valid snapshot')
    when=date(t)
    if abs((datetime.now(timezone.utc)-when).total_seconds())>18000:raise SystemExit('Stale snapshot')
    quotes={q['symbol']:q for q in data['signals'] if float(q.get('price') or 0)>0}
    btc=quotes.get('BTCUSDT')
    market_ok=bool(btc and float(btc['price'])>float(btc['ema50']) and float(btc['ema20'])>float(btc['ema50']) and float(btc['change24h_pct'])>-2)
    s=json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {'version':1,'strategy':'B - dynamic','started_at_utc':t,'duration_days':30,'start_capital_usdt':500,'fee_per_side_pct':.5,'positions':[],'events':[],'equity_history':[]}
    deliver(s)
    if when<=date(s.get('last_processed_scan_utc','1970-01-01T00:00:00+00:00')):
        print('B already processed');return
    end=date(s['started_at_utc'])+timedelta(days=30)
    for p in s['positions']:
        if p['status']!='open':continue
        q=quotes.get(p['symbol'])
        if not q:continue
        price=float(q['price']);p['last_price']=price;p['high_price']=max(p['high_price'],price)
        gain=(price/p['entry_price']-1)*100
        atr=float(q.get('atr14_pct') or 0)
        trail=max(2,min(6,1.5*atr)) if atr else 3
        stop=max(2,min(5,1.5*atr)) if atr else 3
        p['trailing_pct']=round(trail,3)
        if gain>=5 and not p['partial_taken']:
            pnl=sell(p,.5,price,t,'Realizzo parziale +5%')
            p['partial_taken']=True
            event(s,p['id']+':partial','partial',t,f'🟦 STRATEGIA B — REALIZZO PARZIALE VIRTUALE\n{p["symbol"]}: 50% a {price} USDT\nP/L netto quota: {pnl:+.2f} USDT\nResta 50% con trailing dinamico. Nessun ordine reale.')
        age=(when-date(p['entry_at_utc'])).total_seconds()/3600
        bad=float(q.get('rsi14',50))<40 or (price<float(q['ema20'])<float(q['ema50']))
        reason=None
        if gain<=-stop:reason=f'Stop ATR {stop:.1f}%'
        elif p['partial_taken'] and price<=p['entry_price']/(1-FEE)**2:reason='Pareggio netto residuo'
        elif p['high_price']>p['entry_price'] and price<=p['high_price']*(1-trail/100):reason=f'Trailing ATR {trail:.1f}%'
        elif bad:reason='Deterioramento tecnico'
        elif age>=72 and gain<1:reason='Time stop 72 ore'
        elif when>=end:reason='Fine esperimento'
        if reason and p['status']=='open':
            sell(p,p['remaining_fraction'],price,t,reason)
            event(s,p['id']+':close','exit',t,f'🟦 STRATEGIA B — USCITA VIRTUALE\n{p["symbol"]}: {reason}\nP/L netto totale stimato: {p["realized_pnl_usdt"]:+.2f} USDT\nPrezzo: {price} USDT. Nessun ordine reale.')
    realized=sum(p['realized_pnl_usdt'] for p in s['positions'])
    unrealized=sum(p['notional_usdt']*p['remaining_fraction']*((p['last_price']/p['entry_price'])*(1-FEE)**2-1) for p in s['positions'] if p['status']=='open')
    equity=500+realized+unrealized
    peak=max([500,equity]+[x['equity_usdt'] for x in s['equity_history']])
    dd=(equity/peak-1)*100
    s['equity_history'].append({'time_utc':t,'equity_usdt':round(equity,4),'drawdown_pct':round(dd,3)})
    s['last_drawdown_pct']=round(dd,3);s['market_filter_ok']=market_ok
    paused=dd<=-6
    if paused and not s.get('drawdown_warning_sent'):
        event(s,'risk:'+t,'risk',t,f'🟦 STRATEGIA B — RISCHIO\nDrawdown virtuale {dd:.2f}%. Sospesi nuovi ingressi; posizioni esistenti monitorate.')
    s['drawdown_warning_sent']=paused
    if when<end and market_ok and not paused:
        opened={p['symbol'] for p in s['positions'] if p['status']=='open'}
        cooling={p['symbol'] for p in s['positions'] if p['status']=='closed' and when-date(p['closed_at_utc'])<timedelta(hours=24)}
        eligible=[q for q in quotes.values() if q['symbol']!='BTCUSDT' and q['symbol'] not in opened and q['symbol'] not in cooling and int(q.get('score',0))>=76 and float(q.get('volume_ratio') or 0)>=1.1 and float(q['price'])>float(q['ema20'])>float(q['ema50']) and 45<=float(q['rsi14'])<=68 and float(q.get('atr14_pct') or 0)>0]
        eligible.sort(key=lambda q:(-int(q['score']),-float(q['volume_ratio']),q['symbol']))
        slots=min(2,max(0,5-sum(p['status']=='open' for p in s['positions'])))
        for q in eligible[:slots]:
            symbol=q['symbol'];price=float(q['price'])
            p={'id':symbol+':'+t,'symbol':symbol,'entry_at_utc':t,'entry_price':price,'score_at_entry':int(q['score']),'notional_usdt':100,'high_price':price,'last_price':price,'remaining_fraction':1,'realized_pnl_usdt':0,'partial_taken':False,'status':'open','fills':[]}
            s['positions'].append(p)
            event(s,p['id']+':open','entry',t,f'🟦 STRATEGIA B — INGRESSO VIRTUALE\n{symbol} · score {q["score"]}/100\nPrezzo {price} USDT · volumi {q["volume_ratio"]}x · ATR {q["atr14_pct"]}%\n100 USDT virtuali, filtro BTC favorevole. Nessun ordine reale.')
    s['last_processed_scan_utc']=t;s['last_checked_at_utc']=datetime.now(timezone.utc).isoformat()
    save(s);deliver(s)
    print('B positions',len(s['positions']),'equity',round(equity,2),'market filter',market_ok)
if __name__=='__main__':main()
