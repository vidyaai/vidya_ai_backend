"""
Utility to dynamically fetch available schemdraw elements at runtime.
This ensures we only use elements that actually exist in the installed version.
"""

import inspect
from typing import List, Set


def get_schemdraw_elements() -> Set[str]:
    """
    Dynamically fetch all available schemdraw element names.

    Returns:
        Set of valid element class names (e.g., {'Resistor', 'Capacitor', 'NFet', ...})
    """
    try:
        import schemdraw.elements as elm

        # Get all classes from schemdraw.elements
        elements = set()
        for name, obj in inspect.getmembers(elm):
            # Only include classes, exclude private/internal ones
            if inspect.isclass(obj) and not name.startswith('_'):
                elements.add(name)

        return elements
    except ImportError:
        # Fallback if schemdraw not installed
        return set()


def get_element_categories() -> dict:
    """
    Categorize elements by type for easier reference.

    Returns:
        Dictionary with categories and their elements
    """
    all_elements = get_schemdraw_elements()

    categories = {
        'passive': [],
        'transistors': [],
        'opamps': [],
        'sources': [],
        'power': [],
        'logic': [],
        'connections': [],
        'other': []
    }

    for elem in sorted(all_elements):
        elem_lower = elem.lower()

        if any(x in elem_lower for x in ['resistor', 'capacitor', 'inductor', 'diode', 'zener', 'led']):
            categories['passive'].append(elem)
        elif any(x in elem_lower for x in ['bjt', 'fet', 'jfet', 'mos']):
            categories['transistors'].append(elem)
        elif 'opamp' in elem_lower:
            categories['opamps'].append(elem)
        elif 'source' in elem_lower:
            categories['sources'].append(elem)
        elif any(x in elem_lower for x in ['ground', 'vdd', 'vss', 'antenna']):
            categories['power'].append(elem)
        elif any(x in elem_lower for x in ['and', 'or', 'not', 'nand', 'nor', 'xor', 'buf']):
            categories['logic'].append(elem)
        elif any(x in elem_lower for x in ['line', 'dot', 'gap', 'arrow', 'label']):
            categories['connections'].append(elem)
        else:
            categories['other'].append(elem)

    return categories


def format_elements_for_prompt() -> str:
    """
    Format the available elements as a string for the Claude prompt.

    Returns:
        Formatted string listing all valid elements
    """
    categories = get_element_categories()

    lines = []
    lines.append("VALID SCHEMDRAW ELEMENTS (dynamically verified):")
    lines.append("")

    if categories['passive']:
        lines.append(f"Passive: {', '.join(sorted(categories['passive']))}")

    if categories['transistors']:
        lines.append(f"Transistors: {', '.join(sorted(categories['transistors']))}")

    if categories['opamps']:
        lines.append(f"OpAmps: {', '.join(sorted(categories['opamps']))}")

    if categories['sources']:
        lines.append(f"Sources: {', '.join(sorted(categories['sources']))}")

    if categories['power']:
        lines.append(f"Power/Ground: {', '.join(sorted(categories['power']))}")

    if categories['logic']:
        lines.append(f"Logic Gates: {', '.join(sorted(categories['logic']))}")

    if categories['connections']:
        lines.append(f"Connections: {', '.join(sorted(categories['connections']))}")

    return "\n".join(lines)


def get_common_mistakes() -> List[str]:
    """
    Return list of common element names that DON'T exist but might be assumed.

    Returns:
        List of invalid element names
    """
    all_elements = get_schemdraw_elements()

    # Common mistakes people make
    potential_mistakes = [
        'Mosfet', 'MOSFET', 'PTrans', 'NTrans',
        'Transistor',  # Too generic
        # Note: NMos, PMos, NFet, PFet all exist in schemdraw 0.19+
        # Note: Nand, Nor, And, Or, Not exist in schemdraw.logic (not schemdraw.elements)
    ]

    # Return only those that actually don't exist
    return [m for m in potential_mistakes if m not in all_elements]


if __name__ == "__main__":
    # Test the functions
    print("=" * 60)
    print("SCHEMDRAW ELEMENTS DETECTED")
    print("=" * 60)
    print()
    print(format_elements_for_prompt())
    print()
    print("=" * 60)
    print("COMMON MISTAKES TO AVOID:")
    print("=" * 60)
    invalid = get_common_mistakes()
    for item in invalid:
        print(f"  ❌ elm.{item}() - DOES NOT EXIST")
    print()
    print(f"Total valid elements: {len(get_schemdraw_elements())}")
