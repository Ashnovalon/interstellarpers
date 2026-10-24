#!/usr/bin/env python3
"""Pulp Riot Juice Co. demand x inventory risk engine.
Synthetic replay grounded in supplied case figures; no external data or ML.
Runs offline: python pulp_riot_model.py [--qc-multiplier 4] [--closure-weeks 3] [--pulp-cover-weeks 2]
No action is executed by this script; approvals are recorded as pending.
"""
import argparse, csv, json
from pathlib import Path

F = {
 'Mango Peach Basil':.38, 'Guava Chilli':.20, 'Passionfruit Punch':.16,
 'Dragonfruit Bloom':.14, 'Dragon Passion':.12
}
DEPOTS = [
 ('D1','Delhi','North',.13,True), ('D2','Jaipur','North',.09,False),
 ('D3','Mumbai','West',.16,True), ('D4','Pune','West',.12,True),
 ('D5','Ahmedabad','West',.08,False), ('D6','Bengaluru','South',.16,True),
 ('D7','Chennai','South',.12,False), ('D8','Kolkata','East',.08,False),
 ('D9','Bhubaneswar','East',.06,False),
]
SUMMER_BOTTLES = 96_000_000
WEEKS = 16
PRICE = 60
CM = .32
QC_SHARE = .20
GT_SHARE, MT_SHARE = .55, .25
DAILY_SENSE_DAYS = 2
TRANSIT_COST = 1.5
SUMMER_REVENUE_CRORE = 576

def crore(b): return round(b/10_000_000,3)

def depots(multiplier=4.0):
    hot_w = sum(d[3] for d in DEPOTS if d[4])
    quiet_mult = (multiplier - hot_w * (multiplier+1))/(1-hot_w)
    # For the 4x case this puts a synthetic 5x spike in hot depots
    # and a matching 2.674x spike in other depots; weighted average=4x.
    # More generally hotspot = multiplier + 1, subject to >=1 quiet multiplier.
    if quiet_mult < 1:
        hot_mult=multiplier
        quiet_mult=multiplier
    else:
        hot_mult=multiplier+1
    assert abs(sum(w*(hot_mult if hot else quiet_mult) for _,_,_,w,hot in DEPOTS)-multiplier)<1e-7
    return hot_mult, quiet_mult

def solve(qc_multiplier=4, closure_weeks=3, pulp_cover_weeks=2, opening_age_days=7):
    assert qc_multiplier>=1 and closure_weeks>=0 and pulp_cover_weeks>=0
    hot_qc, quiet_qc=depots(qc_multiplier)
    # Synthetic observed regional variation in Mango and Guava, nationally volume-neutral.
    fast_w=sum(d[3] for d in DEPOTS if d[0] in ('D1','D3','D6'))
    slow_w=sum(d[3] for d in DEPOTS if d[0] in ('D8','D9'))
    normal_factor=(1-fast_w*1.30-slow_w*.65)/(1-fast_w-slow_w)
    rows=[]
    for key,city,region,w,hot in DEPOTS:
        for flavor,mix in F.items():
            base=SUMMER_BOTTLES*mix/WEEKS*w
            if flavor=='Dragon Passion':
                qc_mult=hot_qc if hot else quiet_qc
                real_factor=(1-QC_SHARE)+QC_SHARE*qc_mult
            elif flavor in ('Mango Peach Basil','Guava Chilli'):
                qc_mult=1.0
                real_factor=1.30 if key in ('D1','D3','D6') else (.65 if key in ('D8','D9') else normal_factor)
            else:
                qc_mult=1.0
                real_factor=1.0
            current=base*real_factor
            opening=base*3 # all depot/flavor positions initially on a 3-week static target
            coverage=7*opening/current if current else 999
            min_cover=14
            shortage=max(0.0, current*min_cover/7-opening)
            donor=max(0.0, opening-current*min_cover/7)
            # Exposed bottles for MT/QC (freshness eligibility <30 days from manufacture).
            selling_days=max(0,30-opening_age_days)
            freshness=max(0,opening-current*selling_days/7)*(MT_SHARE+QC_SHARE)
            status='CRITICAL' if coverage<14 else ('WATCH' if coverage>30-opening_age_days else 'OK')
            rows.append(dict(depot=key,city=city,region=region,flavor=flavor,share=w,
                  hotspot=hot,weekly_baseline=round(base),weekly_sensed=round(current),
                  demand_factor=round(real_factor,4),qc_multiplier=round(qc_mult,4),
                  stock_bottles=round(opening),coverage_days=round(coverage,2),
                  shortage_to_14d=round(shortage),donor_above_14d=round(donor),
                  mt_qc_freshness_exposure=round(freshness),flag=status))
    # Two-way match transfer proposals between same-flavor donors and receivers.
    transfers=[]
    for flavor in F:
        group=[r for r in rows if r['flavor']==flavor]
        donors=sorted([r for r in group if r['donor_above_14d']>0],key=lambda r:r['coverage_days'],reverse=True)
        sinks=sorted([r for r in group if r['shortage_to_14d']>0],key=lambda r:r['coverage_days'])
        donor_left={r['depot']:r['donor_above_14d'] for r in donors}
        for sink in sinks:
            remain=sink['shortage_to_14d']
            for d in donors:
                amount=min(remain,donor_left[d['depot']])
                if amount<1000: continue  # proposals less than 1,000 bottles deferred
                amount=int(amount//1000*1000) # shipments in thousand-bottle lots
                if amount==0:continue
                transfers.append({'module':'Inventory / Distribution','trigger':'<14d receiver; >14d donor',
                      'flavor':flavor,'from':d['depot']+' '+d['city'],'to':sink['depot']+' '+sink['city'],
                      'bottles':amount,'cost_rupees':round(amount*TRANSIT_COST),
                      'transport_days':'2–4','approval':'PENDING','reason':'Bridge geography gap; validate recipient shelf-life at arrival'})
                donor_left[d['depot']]-=amount
                remain-=amount
                if remain<1000:break
    base_dp_week=SUMMER_BOTTLES*F['Dragon Passion']/WEEKS
    extra_per_week=base_dp_week*QC_SHARE*(qc_multiplier-1)
    plant_week=25_000_000/4
    base_week=SUMMER_BOTTLES/WEEKS
    headroom=plant_week-base_week
    needs_tradeoff=max(0,extra_per_week-headroom)
    route_gap=max(0,closure_weeks-pulp_cover_weeks)
    min_buffer=closure_weeks # at least closure; decide buffer prospectively pre-season
    gross_stockouts=SUMMER_REVENUE_CRORE*.08
    modeled=[]
    for week in range(1,17):
        if week==1:
            modeled.append({'when':'Pre-season, 8 months before peak','domain':'Supply + Transportation',
                 'trigger':'Route closed in 3/5 summers; one supplier and no alternative road',
                 'signal':'Structural red flag',
                 'recommended':'Seek cover for closure duration PLUS 3-day normal receipt lead; qualify alternative; validate cold storage and working capital',
                 'owner':'Procurement + Supply + Finance','approval':'PENDING'})
        if week==3 and qc_multiplier>=1.5:
            modeled.append({'when':'W3, 48h after QC spike begins','domain':'Demand',
                 'trigger':f'QC orders at {qc_multiplier:.1f}x baseline, 2 consecutive days',
                 'signal':f'+{extra_per_week:,.0f} Dragon Passion bottles/week vs old plan (all-depot illustrative)',
                 'recommended':'Verify reel/promotion and order quality; publish 2-week demand uplift to nine depots; daily refresh',
                 'owner':'Sales + Marketing + Demand Planner','approval':'PENDING'})
            modeled.append({'when':'W3, same decision window','domain':'Inventory + Distribution',
                 'trigger':'Depot cover falls under 14 days; aged stock elsewhere',
                 'signal':f'{sum(r["flag"]=="CRITICAL" for r in rows)} of 45 depot/flavor positions under 14d in stress snapshot',
                 'recommended':'Approve transfer proposals by flavor if freshness on receipt ≥60d; freeze slow-mover replenishment',
                 'owner':'Regional Sales + Supply Planner','approval':'PENDING'})
            modeled.append({'when':'W3, same decision window','domain':'Production + Supply',
                 'trigger':'Viral uplift exceeds fixed in-house slack',
                 'signal':f'+{extra_per_week:,.0f}/week vs {headroom:,.0f}/week headroom; gap {needs_tradeoff:,.0f}/week',
                 'recommended':'Rebalance mix, preserve core SKUs; activate co-packer only if uplift persists (2-week notice; +25% unit production cost)',
                 'owner':'COO + Finance','approval':'PENDING'})
        if week==5 and qc_multiplier>=1.5:
            modeled.append({'when':'W5 earliest, if W3 co-packer request was approved','domain':'Production + Supply',
                 'trigger':'Two-week lead time on co-packer and spike persistence',
                 'signal':'Up to 10% volume at +25% cost versus in-house production',
                 'recommended':'COO + Finance approve only if the uplift persists and material cover is confirmed; protect profitable core assortment',
                 'owner':'COO + Finance + Co-packer','approval':'PENDING'})
        if week==10:
            modeled.append({'when':'W10, highway closure notification','domain':'Supply + Transportation',
                  'trigger':f'{closure_weeks:g}-week shutdown vs {pulp_cover_weeks:g}-week pulp cover',
                  'signal':f'{route_gap:g} week(s) uncovered while closed; +3-day usual road receipt lag possible',
                  'recommended':'If pre-approved buffer insufficient, ration two passionfruit SKUs by contribution/service and authorize targeted emergency freight only',
                  'owner':'Procurement + COO + Finance','approval':'PENDING'})
    exposure=sum(r['mt_qc_freshness_exposure'] for r in rows)
    transfer_total=sum(t['bottles'] for t in transfers)
    result={
       'case':{'annual_revenue_cr':1200,'summer_revenue_cr':576,'summer_bottles':SUMMER_BOTTLES,
           'lost_stockout_revenue_cr':round(gross_stockouts,2),'lost_stockout_contribution_cr':round(gross_stockouts*CM,2),
           'writeoffs_discounts_cr':6,'airfreight_spend_cr':3.2,
           'airfreight_incremental_cr_if_same_volume':round(3.2*(1-1/5),2),
           'plant_capacity_bottles_week_illustrative':plant_week},
       'controls':{'qc_multiplier':qc_multiplier,'closure_weeks':closure_weeks,'pulp_cover_weeks':pulp_cover_weeks,
           'opening_age_days':opening_age_days},
       'metrics':{'dragon_passion_weekly_baseline':round(base_dp_week),
           'dragon_passion_incremental_weekly_bottles':round(extra_per_week),
           'dragon_passion_incremental_two_weeks':round(extra_per_week*2),
           'production_weekly_baseline_bottles':round(base_week),
           'inhouse_slack_weekly':round(headroom),
           'uncovered_weekly_factory_gap':round(needs_tradeoff),
           'passionfruit_road_gap_weeks':route_gap,
           'normal_road_transit_days':3,
           'minimum_full_disruption_cover_days_with_restart_transit':round(closure_weeks*7+3,1),
           'highway_closure_historical_frequency':.6,
           'critical_depot_sku_count':sum(r['flag']=='CRITICAL' for r in rows),
           'watch_count':sum(r['flag']=='WATCH' for r in rows),
           'proposed_transfer_bottles':transfer_total,
           'proposed_transfer_cost_rupees':round(sum(t['cost_rupees'] for t in transfers)),
           'mt_qc_freshness_exposure_bottles_proxy':round(exposure),
           'distribution_channels':'GT55% / MT25% / QC20%',
           'pending_approvals':len(transfers)+len(modeled)},
       'depot_flavor':rows,'transfer_proposals':transfers,'alert_timeline':modeled,
       'limitations':['All depot weights, local shock distribution, shelf age (7d), and spatial skew are illustrative, not observed.',
           'Three-week cover is sampled even for newly launched Dragon Passion; real launch stock is unknown.',
           'Demand quantities represent orders/latent demand: sell-through falls when stockouts censor sales.',
           'Unprotected pulp duration is a time exposure, not a measured bottle shortfall; recipes/BOM are unavailable.',
           'Transfer proposals do not imply goods move. Stakeholder approval + expiry validation are mandatory.',
           'Case-wide losses are not attributable solely to demand/inventory; do not add overlap blindly.']}
    return result


def output_files(out, data):
    out.mkdir(parents=True,exist_ok=True)
    (out/'replay_results.json').write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
    for name,rows in (('depot_flavor_sample.csv',data['depot_flavor']),('proposed_transfers.csv',data['transfer_proposals']),('alerts_and_approvals.csv',data['alert_timeline'])):
        with (out/name).open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]) if rows else ['none']);writer.writeheader();writer.writerows(rows)


def self_test():
    a=solve()
    m=a['metrics']
    assert m['dragon_passion_incremental_weekly_bottles']==432000
    assert m['uncovered_weekly_factory_gap']==182000
    assert m['passionfruit_road_gap_weeks']==1
    assert len(a['depot_flavor'])==45
    assert sum(r['weekly_baseline'] for r in a['depot_flavor'])==6_000_000 or abs(sum(r['weekly_baseline'] for r in a['depot_flavor'])-6_000_000)<30
    assert all(x['approval']=='PENDING' for x in a['transfer_proposals']+a['alert_timeline'])
    assert abs(sum(w for _,_,_,w,_ in DEPOTS)-1)<1e-9
    assert solve(qc_multiplier=1,closure_weeks=2,pulp_cover_weeks=2)['metrics']['uncovered_weekly_factory_gap']==0
    assert solve(qc_multiplier=1,closure_weeks=2,pulp_cover_weeks=2)['metrics']['passionfruit_road_gap_weeks']==0
    print('PASS: 9 depots × 5 flavors, cost maths, stress scenarios, approval gate')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--qc-multiplier',type=float,default=4)
    p.add_argument('--closure-weeks',type=float,default=3)
    p.add_argument('--pulp-cover-weeks',type=float,default=2)
    p.add_argument('--out',default=str(Path(__file__).resolve().parent))
    p.add_argument('--test',action='store_true')
    args=p.parse_args()
    if args.test:self_test()
    results=solve(args.qc_multiplier,args.closure_weeks,args.pulp_cover_weeks)
    output_files(Path(args.out),results)
    print(json.dumps({'metrics':results['metrics'],'case':results['case']},indent=2))
