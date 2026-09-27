"""EVIDENCE domain — the Evidence Platform (V12 §9).

Facts and the deterministic sets assembled from them: every claim that backs a
Decision is a row here, hashed at write time and immutable forever. Superseded
facts are NEW rows, never edits — the set hash would not survive an edit.
"""
