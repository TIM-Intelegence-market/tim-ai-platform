# Qualification daily manifests

No daily manifest exists because `V2_PROSPECTIVE_QUALIFICATION_V1` has not
started. The PostgreSQL security start gate is failed and the remaining
technical start gates have not yet been frozen on one verified commit.

After an explicit, valid activation, `scripts/v2_qualification_monitor.py`
creates at most one immutable JSON manifest per UTC day in this directory.
It refuses to create evidence before activation and refuses to overwrite a
different manifest for an existing UTC date.
