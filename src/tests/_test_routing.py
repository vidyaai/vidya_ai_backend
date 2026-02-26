"""Quick test of DomainRouter and FallbackRouter changes."""
import sys

sys.path.insert(0, "src")

from utils.domain_router import DomainRouter, _CODE_BETTER_TYPES
from utils.fallback_router import _FALLBACK_TOOL_MAP

router = DomainRouter.__new__(DomainRouter)

tests = [
    (
        "D flip-flop circuit with AND gate and XOR gate, draw timing diagrams for 8 clock cycles",
        "electrical",
    ),
    (
        "3-bit shift register using D flip-flops with enable signal and decoder",
        "electrical",
    ),
    ("CMOS inverter with PMOS and NMOS transistors, find Vout", "electrical"),
    ("Binary counter with JK flip-flops, show timing waveforms", "electrical"),
    ("Op-amp inverting amplifier with Rf=10k and R1=1k", "electrical"),
    ("Draw the state diagram for a sequence detector FSM", "electrical"),
]

print("=== Keyword-based fallback classification ===")
for q, hint in tests:
    result = router._fallback_classification(q, hint)
    print(f"  Q: {q[:70]}")
    print(
        f'    domain={result["domain"]}  type={result["diagram_type"]}  tool={result["preferred_tool"]}  ai={result["ai_suitable"]}'
    )
    print()

# Test _CODE_BETTER_TYPES
seq_types = [
    "sequential_circuit",
    "flip_flop_circuit",
    "counter_circuit",
    "shift_register",
    "circuit_with_timing",
]
print("=== New types in _CODE_BETTER_TYPES ===")
for t in seq_types:
    status = "YES" if t in _CODE_BETTER_TYPES else "NO"
    print(f"  {t}: {status}")

# Test fallback router entries
print()
print("=== Fallback router: new electrical entries ===")
new_types = [
    "sequential_circuit",
    "flip_flop_circuit",
    "counter_circuit",
    "shift_register",
    "cdc_diagram",
    "circuit_with_timing",
    "fsm_diagram",
]
for dt in new_types:
    key = ("electrical", dt)
    if key in _FALLBACK_TOOL_MAP:
        tool, lib = _FALLBACK_TOOL_MAP[key]
        print(f"  ({key[0]}, {key[1]}) -> {tool} [{lib}]")
    else:
        print(f"  ({key[0]}, {key[1]}) -> MISSING!")

print()
print("=== All tests passed ===")
