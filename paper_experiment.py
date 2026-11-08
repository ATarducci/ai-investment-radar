#!/usr/bin/env python3
"""30-day public paper-trading experiment. No real money, accounts or user positions."""
import json, os, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT=Path(__file__).parent
LATEST=ROOT/'data/latest.json'
STATE=ROOT/'data/experiment.json'
BOT=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
CHAT=os.getenv('TELEGRAM_CHAT_ID','').strip()
MIN_SCORE=76
TAKE_PROFIT=5.0
STOP_LOSS=-3.0
TRAIL_FROM_HIGH=3.0
CAPITAL=100.0 # USDT, fictional, per signal
MAX_OPEN=5
MAX_NEW_PER_SCAN=2
DURATION_DAYS=30
MAX_STALE_HOURS=5

def utc(s):
    return datetime.fromisoformat(s.replace('Z','+00:00'))

def send(message):
    if not BOT or not CHAT:
        print('Telegram not configured; record-only mode')
        return
    body=urllib.parse.urlencode({'chat_id':CHAT,'text':message,'disable_web_page_preview':'true'}).encode()
    req=urllib.request.Request('https://api.telegram.org/bot'+BOT+'/sendMessage',data=body,method='POST')
    with urllib.request.urlopen(req,timeout=15) as response:
        if not json.load(response).get('ok'):
            raise RuntimeError('Telegram rejected notification')

def save(state):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

def main():
    now=datetime.now(timezone.utc)
    data=json.loads(LATEST.read_text(encoding='utf-8'))
    scan_time=utc(data['generated_at_utc'])
    if abs((now-scan_time).total_seconds())>MAX_STALE_HOURS*3600:
        raise SystemExit('Market data too old: experiment not updated')
    quotes={s['symbol']:s for s in data['signals'] if float(s.get('price',0))>0}
    state=json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {
        'version':1,'started_at_utc':scan_time.isoformat(),'duration_days':DURATION_DAYS,
        'assumed_capital_usdt_per_position':CAPITAL,'assumed_roundtrip_cost_pct':1.0,
        'positions':[],'events':[]}
    started=utc(state['started_at_utc'])
    end=started+timedelta(days=DURATION_DAYS)
    if scan_time<=utc(state.get('last_processed_scan_utc','1970-01-01T00:00:00+00:00')):
        print('Snapshot already processed');return
    def notify_once(event):
        # Persist event BEFORE attempting delivery. Failed deliveries are retried next run.
        event['delivered']=False
        state['events'].append(event)
        save(state)
    def retry_notifications():
        for e in state['events']:
            if e.get('delivered'):continue
            send(e['text'])
            e['delivered']=True
            save(state)
    # Finish previous pending notifications before creating new events.
    retry_notifications()
    for p in state['positions']:
        if p['status']!='open':continue
        q=quotes.get(p['symbol'])
        if q is None:continue
        price=float(q['price'])
        p['last_price']=price
        p['high_price']=max(float(p['high_price']),price)
        change=(price/float(p['entry_price'])-1)*100
        high_change=(price/float(p['high_price'])-1)*100
        p['last_change_pct']=round(change,3)
        reason=None
        if change<=STOP_LOSS:reason='Soglia di perdita -3%'
        elif p['high_price']>p['entry_price'] and high_change<=-TRAIL_FROM_HIGH:reason='Arretramento del 3% dal massimo osservato'
        elif change>=TAKE_PROFIT:reason='Obiettivo di profitto +5%'
        elif scan_time>=end:reason='Fine esperimento 30 giorni'
        if reason:
            p['status']='closed';p['exit_price']=price;p['closed_at_utc']=scan_time.isoformat()
            p['exit_reason']=reason
            # 0.5% each side, fictional cost, no FX, slippage or tax
            p['net_return_pct']=round(((price/p['entry_price'])*(1-.005)**2-1)*100,3)
            event={'id':p['id']+':close','kind':'exit','time_utc':scan_time.isoformat(),
                   'text':f"🧪 RADAR — CHIUSURA VIRTUALE\n{p['symbol']} · {reason}\nRendimento virtuale netto stimato: {p['net_return_pct']:+.2f}%\nPrezzo: {price} USDT\nNessun ordine eseguito. Prezzi campionati, non tick-by-tick."}
            notify_once(event)
    open_positions=[p for p in state['positions'] if p['status']=='open']
    if scan_time<end:
        existing={p['symbol'] for p in state['positions']}
        eligible=sorted((q for q in quotes.values() if int(q.get('score',0))>=MIN_SCORE and q['symbol'] not in existing),key=lambda q:(-int(q['score']),q['symbol']))
        slots=max(0,min(MAX_NEW_PER_SCAN,MAX_OPEN-len(open_positions)))
        for q in eligible[:slots]:
            symbol=q['symbol'];price=float(q['price'])
            position={'id':symbol+':'+scan_time.isoformat(),'symbol':symbol,
                'entry_price':price,'entry_at_utc':scan_time.isoformat(),
                'score_at_entry':int(q['score']),'high_price':price,
                'last_price':price,'last_change_pct':0,'status':'open',
                'notional_usdt':CAPITAL}
            state['positions'].append(position)
            event={'id':position['id']+':open','kind':'entry','time_utc':scan_time.isoformat(),
                'text':f"🧪 RADAR — NUOVA POSIZIONE VIRTUALE\n{symbol} · score {q['score']}/100\nPrezzo osservato: {price} USDT\nCapitale fittizio: 100 USDT\nObiettivo +5%, soglia -3%, trailing 3%\nNon è un suggerimento personalizzato né un ordine di acquisto."}
            notify_once(event)
    state['last_processed_scan_utc']=scan_time.isoformat()
    state['last_checked_at_utc']=now.isoformat()
    save(state)
    retry_notifications()
    print('Experiment positions:',len(state['positions']),'events:',len(state['events']))

if __name__=='__main__':
    main()
