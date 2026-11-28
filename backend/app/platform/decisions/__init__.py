"""DECISIONS domain — the Decision Plane (V12 §): decisions + dependencies.

Every sensitive mutation mints a Decision (ADR-060: human actors included).
The decision row is the durable record of WHAT was about to happen, on WHAT
evidence, against WHICH resource versions — and the explicit state machine
below is the only path any status may travel.
"""
