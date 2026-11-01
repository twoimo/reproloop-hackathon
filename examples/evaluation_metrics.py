"""Typed OFFLINE metric aggregation, not an Android oracle/authenticator.

A correct faulty-positive/fixed-negative PAIR has verdict CONFIRMED. That is
not a false positive on the fixed run. Keep each denominator at its own level.
All row fields must come from trusted run/evidence validation in production.
"""
from dataclasses import dataclass
from repro_oracle import Verdict

@dataclass(frozen=True)
class EvaluationRow:
    case_id: str
    export_created: bool
    faulty_complete: bool
    faulty_failure: bool | None
    fixed_complete: bool  # workflow + own fixed-run identity/reset checked; signal may still be unknown
    fixed_failure: bool | None
    pair_binding_valid: bool  # script/task/fixture/build/reset/no-LLM evidence
    pair_verdict: Verdict


def summarize(rows: list[EvaluationRow], planned_case_ids: list[str]) -> dict:
    if not isinstance(rows,list) or not isinstance(planned_case_ids,list):
        raise ValueError('expected lists')
    if any(not isinstance(x,str) or not x.strip() or len(x)>120 for x in planned_case_ids):
        raise ValueError('invalid planned case id')
    if len(planned_case_ids)!=len(set(planned_case_ids)):
        raise ValueError('duplicate planned case')
    seen=set(); valid=invalid_confirmed=fixed_positive=fixed_known=0
    for row in rows:
        if not isinstance(row,EvaluationRow):raise ValueError('invalid row type')
        if not isinstance(row.case_id,str) or row.case_id not in planned_case_ids or row.case_id in seen:
            raise ValueError('unexpected or duplicate result case')
        seen.add(row.case_id)
        if any(type(x) is not bool for x in (row.export_created,row.faulty_complete,row.fixed_complete,row.pair_binding_valid)):
            raise ValueError('flags must be exact bool')
        if any(x is not None and type(x) is not bool for x in (row.faulty_failure,row.fixed_failure)):
            raise ValueError('signals must be bool or None')
        if not isinstance(row.pair_verdict,Verdict):raise ValueError('invalid typed pair verdict')
        fixed_has_signal=row.fixed_complete and type(row.fixed_failure) is bool
        fixed_known+=int(fixed_has_signal)
        fixed_positive+=int(fixed_has_signal and row.fixed_failure is True)
        evidence_valid=(row.export_created and row.faulty_complete and row.faulty_failure is True
            and row.fixed_complete and row.fixed_failure is False and row.pair_binding_valid)
        confirmed=row.pair_verdict is Verdict.CONFIRMED
        valid+=int(evidence_valid and confirmed)
        invalid_confirmed+=int(confirmed and not evidence_valid)
    # Missing executions remain explicit rows, never vanish from denominator.
    if seen!=set(planned_case_ids):raise ValueError('all planned cases need a result, including missing/inconclusive')
    n=len(planned_case_ids)
    fraction=lambda a,b:f'{a}/{b}' if b else None
    return {
        'primary_valid_export_pairs':{'count':valid,'planned':n,'fraction':fraction(valid,n)},
        'fixed_failure_signals':{'positive':fixed_positive,'complete_with_signal':fixed_known,
            'missing_or_unknown':n-fixed_known,'fraction':fraction(fixed_positive,fixed_known)},
        'invalid_pair_confirmations':{'count':invalid_confirmed,'evaluated_pairs':n,
            'fraction':fraction(invalid_confirmed,n)},
        'limits':'Aggregates typed evidence records only. A fixed positive may mean broken fix/setup/oracle; not a measured detector false-positive rate without independent reference truth.'}


def synthetic_worked_example() -> dict:
    good=lambda case:EvaluationRow(case,True,True,True,True,False,True,Verdict.CONFIRMED)
    rows=[good('P01'),good('P02'),good('P03'),
        EvaluationRow('P04',False,False,None,False,None,False,Verdict.INCONCLUSIVE),
        EvaluationRow('P05',True,True,True,False,None,False,Verdict.INCONCLUSIVE)]
    return {'evidence_level':'SYNTHETIC_MOCK_TESTED','actual_pilot_runs':0,
            **summarize(rows,['P01','P02','P03','P04','P05'])}

if __name__=='__main__':
    import json
    print(json.dumps(synthetic_worked_example(),indent=2))
