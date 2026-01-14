import json
import math
from typing import Any, Dict, List

def load_json(path: str) -> Any:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: File not found at {path}")
        return []

def normalize_string(s: Any) -> str:
    if s is None:
        return "null"
    return str(s).strip().upper()

def compare_floats(val1: Any, val2: Any) -> bool:
    if val1 is None and val2 is None:
        return True
    if val1 is None or val2 is None:
        return False
    try:
        return round(float(val1), 2) == round(float(val2), 2)
    except (ValueError, TypeError):
        return False

def compare_values(field: str, val1: Any, val2: Any) -> bool:
    if field in ['cargo_weight_kg', 'cargo_cbm']:
        return compare_floats(val1, val2)
    
    # Strict matching for other fields, treating None as explicit 'null'
    s1 = normalize_string(val1)
    s2 = normalize_string(val2)
    return s1 == s2

def evaluate_accuracy(output_path: str, ground_truth_path: str):
    outputs = {item['id']: item for item in load_json(output_path)}
    ground_truth = {item['id']: item for item in load_json(ground_truth_path)}

    if not outputs:
        print("No output data found to evaluate.")
        return

    fields_to_evaluate = [
        "product_line",
        "origin_port_code",
        "origin_port_name",
        "destination_port_code",
        "destination_port_name",
        "incoterm",
        "cargo_weight_kg",
        "cargo_cbm",
        "is_dangerous"
    ]

    total_fields = 0
    correct_fields = 0
    field_metrics = {f: {'correct': 0, 'total': 0} for f in fields_to_evaluate}

    print(f"\n{'='*60}")
    print(f"{'EVALUATION REPORT':^60}")
    print(f"{'='*60}\n")

    for email_id, truth in ground_truth.items():
        if email_id not in outputs:
            print(f"Warning: Email {email_id} missing in output.")
            continue
        
        pred = outputs[email_id]
        
        for field in fields_to_evaluate:
            truth_val = truth.get(field)
            pred_val = pred.get(field)
            
            is_correct = compare_values(field, truth_val, pred_val)
            
            field_metrics[field]['total'] += 1
            total_fields += 1
            
            if is_correct:
                field_metrics[field]['correct'] += 1
                correct_fields += 1
            else:
                pass

    print(f"{'Field':<25} | {'Accuracy':<10} | {'Correct/Total'}")
    print("-" * 50)
    
    for field, metrics in field_metrics.items():
        acc = (metrics['correct'] / metrics['total'] * 100) if metrics['total'] > 0 else 0.0
        print(f"{field:<25} | {acc:6.2f}%    | {metrics['correct']}/{metrics['total']}")

    overall_acc = (correct_fields / total_fields * 100) if total_fields > 0 else 0.0
    print(f"\n{'='*60}")
    print(f"OVERALL ACCURACY: {overall_acc:.2f}% ({correct_fields}/{total_fields})")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    evaluate_accuracy('output.json', 'ground_truth.json')
