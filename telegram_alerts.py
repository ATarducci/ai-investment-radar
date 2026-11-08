#!/usr/bin/env python3
"""Telegram alerts from public scanner snapshots. No orders or private holdings."""
import json, os, urllib.parse, urllib.request
from pathlib import Path
ROOT=Path(__file__).parent
DATA=ROOT/'data/latest.json'
STATE=ROOT/'data/alert_state.json'
BOT=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
CHAT=os.getenv('TELEGRAM_CHAT_ID','').strip()
MIN_SCORE=int(os.getenv('ALERT_MIN_SCORE','76'))
MAX_ALERTS=3

def send(message):
    if not BOT or not CHAT:
        print('Telegram secrets not configured; skipping alerts')
        return False
    payload=urllib.parse.urlencode({'chat_id':CHAT,'text':message,'disable_web_page_preview':'true'}).encode()
    req=urllib.request.Request('https://api.telegram.org/bot'+BOT+'/sendMessage',data=payload,method='POST')
    with urllib.request.urlopen(req,timeout=15) as response:
        obj=json.load(response)
    if not obj.get('ok'):
        raise RuntimeError('Telegram returned unsuccessful response')
    return True

def main():
    if not BOT or not CHAT:
        print('Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID');return
    if not DATA.exists():
        print('No scanner data');return
    data=json.loads(DATA.read_text())
    if not data.get('generated_at_utc') or not data.get('signals'):
        print('No valid market snapshot');return
    previous=json.loads(STATE.read_text()) if STATE.exists() else {'active':[]}
    old=set(previous.get('active',[]))
    eligible=[x for x in data['signals'] if int(x.get('score',0))>=MIN_SCORE]
    current={x['symbol'] for x in eligible}
    newly=[x for x in eligible if x['symbol'] not in old][:MAX_ALERTS]
    for x in newly:
        message=('📊 AI Investment Radar — segnale tecnico da valutare\n'
                 f"{x['symbol']} | score {x['score']}/100\n"
                 f"Prezzo rilevato: {x['price']} USDT\n"
                 f"Variazione 24h: {x['change24h_pct']}% | RSI: {x['rsi14']}\n"
                 f"Scansione UTC: {data['generated_at_utc']}\n"
                 'Non è una raccomandazione di acquisto; il segnale non predice un rialzo. '
                 'Verifica costi, disponibilità e rischi prima di qualsiasi decisione.\n'
                 'https://atarducci.github.io/ai-investment-radar/opportunities.html')
        if send(message):
            print('Sent signal',x['symbol'])
    # Only mark signals as notified after all sends succeeded; unnotified new signals remain eligible next scan.
    notified=set(old)&current
    notified.update(x['symbol'] for x in newly)
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps({'active':sorted(notified),'last_scan_utc':data['generated_at_utc']},indent=2)+'\n')
    print('Telegram alert cycle completed')

if __name__=='__main__':
    main()
