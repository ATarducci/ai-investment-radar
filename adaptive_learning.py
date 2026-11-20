"""Adaptive shadow research: predeclared variants, forward-only holdout, no orders."""
import json, math
from pathlib import Path
from datetime import datetime, timedelta, timezone
ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'
OUT=DATA/'adaptive.json'
RULES={'control':(76,1.1,True),'volume_strict':(76,1.5,True),'market_relaxed':(76,1.1,False),'score_strict':(82,1.1,True)}
def dt(x):return datetime.fromisoformat(x.replace('Z','+00:00'))
def net(a,b):return 100*((b/a)*.995**2-1)
def main():
    d=json.loads((DATA/'latest.json').read_text())
    t=d['generated_at_utc']; now=dt(t)
    if d.get('status')!='ok' or abs((datetime.now(timezone.utc)-now).total_seconds())>18000:return
    s=json.loads(OUT.read_text()) if OUT.exists() else {'version':1,'start':t,'variants':{k:[] for k in RULES},'active':'control','reviews':[]}
    if t<=s.get('last_scan',''):return
    q={x['symbol']:x for x in d['signals'] if x.get('price',0)>0}
    btc=q.get('BTCUSDT')
    market=bool(btc and btc['price']>btc['ema50'] and btc['ema20']>btc['ema50'] and btc['change24h_pct']>-2)
    for name,(score,volume,need_market) in RULES.items():
        trades=s['variants'][name]
        for p in trades:
            if p['status']!='open' or p['symbol'] not in q:continue
            x=q[p['symbol']];price=x['price'];p['high']=max(p['high'],price);p['low']=min(p['low'],price)
            gain=100*(price/p['entry']-1)
            age=(now-dt(p['opened'])).total_seconds()/3600
            reason='profit' if gain>=5 else 'loss' if gain<=-3 else 'trailing' if price<=p['high']*.97 else 'time' if age>=72 else None
            if reason:
                p.update(status='closed',closed=t,exit=price,net_pct=round(net(p['entry'],price),4),reason=reason)
        opened={p['symbol'] for p in trades if p['status']=='open'}
        cooling={p['symbol'] for p in trades if p['status']=='closed' and now-dt(p['closed'])<timedelta(hours=24)}
        candidates=[x for x in q.values() if x['symbol']!='BTCUSDT' and x['symbol'] not in opened|cooling and x['score']>=score and (x.get('volume_ratio') or 0)>=volume and x['price']>x['ema20']>x['ema50'] and 45<=x['rsi14']<=68 and (market or not need_market)]
        candidates.sort(key=lambda x:(-x['score'],-x['volume_ratio'],x['symbol']))
        for x in candidates[:min(2,max(0,5-len(opened)))]:
            trades.append({'symbol':x['symbol'],'opened':t,'entry':x['price'],'high':x['price'],'low':x['price'],'status':'open','context':{'score':x['score'],'volume':x['volume_ratio'],'rsi':x['rsi14'],'atr':x.get('atr14_pct'),'btc_change':btc['change24h_pct'] if btc else None,'market_ok':market}})
    # Fixed chronological train / holdout split. No promotion based on individual losses.
    split=dt(s['start'])+timedelta(days=30)
    metrics={}
    for k,trades in s['variants'].items():
        closed=[p for p in trades if p['status']=='closed']
        def stats(rows):
            vals=[p['net_pct'] for p in rows];wins=sum(v>0 for v in vals)
            return {'n':len(vals),'mean_net_pct':round(sum(vals)/len(vals),4) if vals else None,'win_rate':round(wins/len(vals)*100,2) if vals else None,'sum_net_pct':round(sum(vals),4)}
        train=[p for p in closed if dt(p['closed'])<split]
        test=[p for p in closed if dt(p['opened'])>=split]
        metrics[k]={'all':stats(closed),'train':stats(train),'holdout':stats(test),'open':sum(p['status']=='open' for p in trades)}
    s['metrics']=metrics
    # Diagnostic hypotheses, not causal attribution.
    losses=[]
    for p in s['variants']['control']:
        if p['status']=='closed' and p['net_pct']<0:
            c=p['context'];tags=[]
            if c['volume']<1.5:tags.append('volume moderato')
            if c['rsi']>60:tags.append('RSI elevato')
            if c['atr'] and c['atr']>2:tags.append('volatilita elevata')
            if p['high']/p['entry']>1.02:tags.append('profitto potenziale poi perso')
            losses.append({'symbol':p['symbol'],'closed':p['closed'],'net_pct':p['net_pct'],'exit_reason':p['reason'],'hypotheses':tags})
    s['loss_diagnostics']=losses
    s['last_scan']=t
    s['validation_status']='collecting' if now<split+timedelta(days=30) else 'review_required'
    # One preregistered selection using training only, then independent forward validation.
    if now>=split and 'candidate' not in s:
        eligible=[k for k in RULES if k!='control' and metrics[k]['train']['n']>=30 and metrics['control']['train']['n']>=30 and metrics[k]['train']['mean_net_pct']>max(0,metrics['control']['train']['mean_net_pct']+.25)]
        s['candidate']=max(eligible,key=lambda k:metrics[k]['train']['mean_net_pct']) if eligible else None
    if now>=split+timedelta(days=30) and not s.get('decision_finalized'):
        k=s.get('candidate')
        if k:
            a=metrics['control']['holdout'];b=metrics[k]['holdout']
            if a['n']>=30 and b['n']>=30 and b['mean_net_pct']>max(0,a['mean_net_pct']+.25):
                s['active']=k
                s['reviews'].append({'time':t,'decision':'shadow_reference_updated','variant':k,'reason':'Positive mean and improvement over control in chronological holdout'})
            else:
                s['reviews'].append({'time':t,'decision':'retain_control','reason':'Insufficient holdout evidence or improvement'})
        else:
            s['reviews'].append({'time':t,'decision':'retain_control','reason':'No qualified training candidate'})
        s['decision_finalized']=True
    s['note']='Automatic selection changes research reference only, never A/B trading rules. Identical fixed exits; correlated observations, unequal exposure and execution costs limit inference.'
    OUT.write_text(json.dumps(s,indent=2,ensure_ascii=False)+'\n')
if __name__=='__main__':main()
