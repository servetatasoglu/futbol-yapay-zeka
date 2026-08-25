import json
import numpy as np

def run_audit():
    with open('/Users/servet/Desktop/claod futbol/data/clv_bet_log.json', 'r') as f:
        bets = json.load(f).get('bahisler', [])
    
    total_bets = len(bets)
    print(f"Total Bets: {total_bets}")
    
    # Step 1: Data Validation
    has_defaults = any(b.get("oran_alinma", 0) == 4.68 for b in bets)
    has_closing = any(b.get("oran_kapanis") is not None for b in bets)
    missing_closing_count = sum(1 for b in bets if b.get("oran_kapanis") is None)
    has_results = any(b.get("sonuc") is not None for b in bets)
    
    print(f"Has Default Odds (4.68): {has_defaults}")
    print(f"Missing Closing Odds Count: {missing_closing_count}")
    print(f"Has Profit Tracking (Results): {has_results}")
    
    # Step 2: CLV Analysis
    clv_list = []
    beating_closing = 0
    for b in bets:
        o = b.get("oran_alinma")
        c = b.get("oran_kapanis")
        if o is not None and c is not None and c > 0:
            clv = (o / c) - 1
            clv_list.append(clv)
            if clv > 0:
                beating_closing += 1
                
    avg_clv = np.mean(clv_list) if clv_list else 0
    beat_pct = (beating_closing / len(clv_list)) * 100 if clv_list else 0
    print(f"Average CLV: {avg_clv*100:.2f}%")
    print(f"% Beating Closing Line: {beat_pct:.2f}%")
    
    # Step 3: Profitability Test
    roi_list = []
    unit_profit = 0
    wins = 0
    resolved_bets = 0
    actual_profit = 0
    ev_total = 0
    
    for b in bets:
        res = b.get("sonuc")
        odds = b.get("oran_alinma", 1)
        model_p = b.get("model_p", 0)
        
        if res is not None:
            resolved_bets += 1
            if str(res).lower() in ['kazandi', 'kazandı', 'w', 'win', 'true']:
                wins += 1
                unit_profit += (odds - 1)
                actual_profit += (odds - 1)
            elif str(res).lower() in ['iade', 'void', 'v']:
                pass
            else:
                unit_profit -= 1
                actual_profit -= 1
                
            ev_total += (model_p * odds) - 1
            
    win_rate = (wins / resolved_bets * 100) if resolved_bets else 0
    roi = (actual_profit / resolved_bets * 100) if resolved_bets else 0
    print(f"Resolved Bets: {resolved_bets}")
    print(f"Total ROI: {roi:.2f}%")
    print(f"Unit Profit: {unit_profit:.2f}")
    print(f"Win Rate: {win_rate:.2f}%")
    print(f"Expected Profit (EV): {ev_total:.2f}")
    
    # Bootstrap simulation
    if resolved_bets > 0:
        actual_results = []
        for b in bets:
            res = b.get("sonuc")
            odds = b.get("oran_alinma", 1)
            if res is not None:
                if str(res).lower() in ['kazandi', 'kazandı', 'w', 'win', 'true']:
                    actual_results.append(odds - 1)
                elif str(res).lower() in ['iade', 'void', 'v']:
                    actual_results.append(0)
                else:
                    actual_results.append(-1)
                    
        actual_results = np.array(actual_results)
        sim_rois = []
        for _ in range(1000):
            sample = np.random.choice(actual_results, size=len(actual_results), replace=True)
            sim_rois.append(np.mean(sample) * 100)
            
        ci_lower = np.percentile(sim_rois, 2.5)
        ci_upper = np.percentile(sim_rois, 97.5)
        print(f"95% CI ROI: [{ci_lower:.2f}%, {ci_upper:.2f}%]")
    
    # Step 4: Model Calibration
    if resolved_bets > 0:
        avg_model_p = np.mean([b.get("model_p", 0) for b in bets if b.get("sonuc") is not None]) * 100
        print(f"Predicted Win Rate: {avg_model_p:.2f}%")
        print(f"Actual Win Rate: {win_rate:.2f}%")
        print(f"Calibration Deviation: {abs(avg_model_p - win_rate):.2f}%")
    
    # Step 5: Bias Detection
    draw_bets = sum(1 for b in bets if str(b.get("tahmin", "")).lower() in ['beraberlik', 'draw', 'x'])
    draw_pct = (draw_bets / total_bets) * 100 if total_bets else 0
    print(f"Draw Bet Percentage: {draw_pct:.2f}%")
    
    odds_list = [b.get("oran_alinma", 0) for b in bets]
    repeated_odds = len(odds_list) - len(set(odds_list))
    print(f"Repeated Odds Values Count: {repeated_odds}")
    
    # Step 6: Edge Validation
    true_ev_bets = 0
    for b in bets:
        model_p = b.get("model_p", 0)
        odds = b.get("oran_alinma", 1)
        if (model_p * odds) - 1 > 0:
            true_ev_bets += 1
            
    print(f"True EV > 0 Bets: {true_ev_bets}/{total_bets}")
    
run_audit()
