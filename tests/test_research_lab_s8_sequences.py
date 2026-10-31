"""S8 sequence identities, causality, paired evaluation and hard holdout guards."""
from datetime import date
from pathlib import Path
import json

import pytest

from src.research_lab.data.store import HoldoutLocked
from src.research_lab.orderflow_ml.bars import E8, TradeTick, reduce_trades, reduce_trades_with_profile
from src.research_lab.orderflow_ml.features import BASE_FEATURE_NAMES, FEATURE_NAMES, BarSeries, features_at, sequence_features
from src.research_lab.orderflow_ml.sequence_study import (cohort_days, digest, make_plan, paired_month_bootstrap,
                                                         per_row_scores, read_plan, write_plan)
from src.research_lab.orderflow_ml.store import day_start_ms


def bars_for(signs, *, times=None, quantities=None):
    start = day_start_ms(date(2021, 1, 1))
    ticks = [TradeTick(i+1, 100*E8, (quantities or [E8]*len(signs))[i],
                       start + (times or [i*1000 for i in range(len(signs))])[i], s < 0)
             for i, s in enumerate(signs)]
    return reduce_trades(ticks, start)[0]


def test_same_original_minute_different_sequences():
    a, b = bars_for([1]*5+[-1]*5)[0], bars_for([1,-1]*5)[0]
    assert a.as_row()[:15] == b.as_row()[:15]
    assert sequence_features(a) == pytest.approx((-0.5, 0.8, 0.1))
    assert sequence_features(b) == pytest.approx((-0.1, -1.0, 0.1))
    assert len(BASE_FEATURE_NAMES) == 35 and len(FEATURE_NAMES) == 38


def test_second_bursts_use_fixed_utc_buckets_and_volume_not_counts():
    a = bars_for([1,-1,1], times=[999,1000,1999], quantities=[E8,2*E8,3*E8])[0]
    assert sequence_features(a)[2] == pytest.approx(5/6)
    assert sequence_features(bars_for([1]*5)[0]) == pytest.approx((1,0,0.2))
    assert sequence_features(bars_for([1])[0])[1] is None
    assert sequence_features(bars_for([1,-1])[0])[1] is None
    assert sequence_features(bars_for([])[0]) == (None,None,None)


def test_no_run_carry_across_minutes_or_future_changes():
    first = bars_for([1]*3, times=[1000,2000,3000])[0]
    both = bars_for([1]*6, times=[1000,2000,3000,61000,62000,63000])
    assert both[0] == first
    assert both[1].signed_tail_run == 3
    assert sequence_features(both[1])[0] == 1


def test_full_original_feature_vector_is_unchanged_between_equal_aggregate_sequences():
    start=day_start_ms(date(2021,1,1))
    def series(signs):
        bars,profiles=[],{}
        for d in range(2):
            day=start+d*86_400_000
            ticks=(TradeTick(m*10+j+1,(10000+d*1440+m)*E8,E8,day+m*60000+j*1000,s<0)
                   for m in range(1440) for j,s in enumerate(signs))
            b,_,profile=reduce_trades_with_profile(ticks,day)
            bars.extend(b);profiles[day]=profile
        return BarSeries(bars,profiles)
    a,b=series([1]*5+[-1]*5),series([1,-1]*5)
    for i in (1440,1600,2879):
        fa,fb=features_at(a,i),features_at(b,i)
        assert fa.complete and fb.complete
        assert fa.values[:35] == fb.values[:35]
        assert fa.values[35:] != fb.values[35:]


def test_duplicate_ticks_do_not_inflate_sequence_or_burst():
    start=day_start_ms(date(2021,1,1))
    ticks=[TradeTick(i+1,100*E8,E8,start+1000*i,s<0) for i,s in enumerate([1,-1,1])]
    a=reduce_trades(ticks,start)[0]
    b=reduce_trades([ticks[0],ticks[0],*ticks[1:]],start)[0]
    assert a == b


def test_correlation_matches_direct_definition():
    np=pytest.importorskip('numpy')
    rng=np.random.default_rng(16)
    for size in (3,10,100,1000):
        signs=rng.choice([-1,1],size=size)
        got=sequence_features(bars_for(signs.tolist(),times=list(range(size)))[0])[1]
        x,y=signs[:-1],signs[1:]
        expected=float(np.corrcoef(x,y)[0,1]) if np.std(x) and np.std(y) else 0
        assert got == pytest.approx(expected)


def test_cohort_fixed_and_plan_refuses_any_holdout_before_fetch(tmp_path):
    days=cohort_days()
    assert len(days)==480 and len(set(days))==480
    assert all(date(2020,1,1)<=d<date(2025,1,1) for d in days)
    assert days==cohort_days()
    write_plan(tmp_path,0.01)
    assert read_plan(tmp_path)['plan']==make_plan()
    with pytest.raises(ValueError,match='frozen plan'):
        write_plan(tmp_path,0.005)
    envelope=json.loads((tmp_path/'plan.json').read_text())
    envelope['plan']['cohort'].append('2025-01-01')
    envelope['plan_sha256']=digest(envelope['plan'])
    (tmp_path/'plan.json').write_text(json.dumps(envelope))
    with pytest.raises(ValueError,match='mismatch'):
        read_plan(tmp_path)


def test_paired_scores_and_bootstrap_keep_identical_prediction_difference_zero():
    np=pytest.importorskip('numpy')
    y=np.array([0,1,2,1])
    p=np.array([[.8,.1,.1],[.2,.7,.1],[.1,.1,.8],[.1,.8,.1]])
    loss,metrics=per_row_scores(y,p)
    assert metrics['accuracy']==1
    days=np.array(['2023-01-02','2023-01-03','2023-02-02','2023-02-03'])
    same=paired_month_bootstrap(loss,loss,days,replicates=100)
    assert same['ci95']==[0,0] and same['relative_gain']==0 and same['clusters']==2
    better=paired_month_bootstrap(loss,loss*.9,days,replicates=100)
    assert better['relative_gain']==pytest.approx(.1)
    assert better['ci95']==pytest.approx([.1,.1])
    with pytest.raises(ValueError,match='paired'):
        paired_month_bootstrap(loss,loss[:-1],days)
    with pytest.raises(ValueError,match='positive baseline'):
        paired_month_bootstrap(loss*0,loss*0,days)


def test_existing_result_refuses_rerun_before_opening_export_or_fitting(tmp_path):
    from src.research_lab.orderflow_ml.sequence_study import compare
    write_plan(tmp_path,0.01)
    (tmp_path/'result.json').write_text('{"original":true}')
    with pytest.raises(FileExistsError):
        compare(tmp_path)
    assert (tmp_path/'result.json').read_text() == '{"original":true}'
