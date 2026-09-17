"""Business modules.

Rule: a module never queries another module's tables directly — cross-module
work goes through the owning module's application services. This is what keeps
the modular monolith extractable into standalone services later.
"""
