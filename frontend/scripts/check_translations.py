#!/usr/bin/env python3
import os
import re
import json
import sys

# Allowed literal values that do not need translation (common acronyms, units, names)
ALLOWED_LITERALS = {
    "bg", "en", "nai", "nai platform", "platform", "jwt", "sql", "ram", "gb", "mb", "cpu", "gpu", "vram", 
    "utc", "id", "csv", "excel", "docker", "redis", "jupyter", "python", "api", "html", "css",
    "x", "y", "w", "h", "o", "a", "b", "c", "d" # single letters often used as math or close indicators
}

# Attributes to check for hardcoded text
TEXT_ATTRIBUTES = {"placeholder", "title", "alt", "label", "aria-label"}

def flatten_dict(d, prefix=""):
    keys = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys.update(flatten_dict(v, key))
        else:
            keys[key] = v
    return keys

def load_translations(base_dir):
    en_path = os.path.join(base_dir, "public", "locales", "en", "translation.json")
    bg_path = os.path.join(base_dir, "public", "locales", "bg", "translation.json")
    
    en_keys = {}
    bg_keys = {}
    
    if os.path.exists(en_path):
        with open(en_path, "r", encoding="utf-8") as f:
            en_keys = flatten_dict(json.load(f))
    else:
        print(f"Warning: English translations not found at {en_path}")
        
    if os.path.exists(bg_path):
        with open(bg_path, "r", encoding="utf-8") as f:
            bg_keys = flatten_dict(json.load(f))
    else:
        print(f"Warning: Bulgarian translations not found at {bg_path}")
        
    return en_keys, bg_keys

def get_line_number(content, index):
    return content.count("\n", 0, index) + 1

def has_hardcoded_text(text):
    # Strip HTML entities
    text = re.sub(r"&[a-zA-Z0-9#]+;", " ", text)
    # Strip whitespace
    text = text.strip()
    if not text:
        return False
    # Must contain at least one alphabetic character (covers Latin and Cyrillic)
    if not any(c.isalpha() for c in text):
        return False
    # Ignore if it is in the allowed literals list
    if text.lower() in ALLOWED_LITERALS:
        return False
    # If it is just a binding var like {someVar}, we shouldn't flag it
    if text.startswith("{") and text.endswith("}"):
        return False
    return True

def analyze_file(filepath, en_keys, bg_keys):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
        
    warnings = []
    
    # 1. Check for t('key') calls and find missing translations
    t_matches = re.finditer(r"\bt\(\s*(?:'([^']+)'|\"([^\"]+)\"|`([^`]+)`)\s*[\),]", content)
    for m in t_matches:
        key = m.group(1) or m.group(2) or m.group(3)
        if key and not ("${" in key):
            line = get_line_number(content, m.start())
            if key not in en_keys:
                warnings.append({
                    "line": line,
                    "type": "Missing Translation Key",
                    "detail": f"Key '{key}' is missing in English translations."
                })
            if key not in bg_keys:
                warnings.append({
                    "line": line,
                    "type": "Missing Translation Key",
                    "detail": f"Key '{key}' is missing in Bulgarian translations."
                })
                
    # 2. JSX Parser state machine
    i = 0
    n = len(content)
    
    state_stack = ["JS"]
    
    def pop_state():
        if len(state_stack) > 1:
            return state_stack.pop()
        return "JS"
        
    string_quote_char = None
    tag_start_idx = -1
    tag_braces_depth = 0
    jsx_braces_depths = []
    is_closing_tag = False
    
    current_jsx_text = []
    current_jsx_text_start = 0
    
    def is_tag_start(idx):
        if idx + 1 >= n:
            return False
        if content[idx] != "<":
            return False
        next_char = content[idx+1]
        return next_char.isalpha() or next_char in ("/", ">", "!")

    while i < n:
        char = content[i]
        curr_state = state_stack[-1]
        
        if curr_state == "COMMENT_LINE":
            if char == "\n":
                pop_state()
            i += 1
            continue
        elif curr_state == "COMMENT_BLOCK":
            if char == "*" and i + 1 < n and content[i+1] == "/":
                pop_state()
                i += 2
            else:
                i += 1
            continue
        elif curr_state == "STRING":
            if char == "\\":
                i += 2
            elif char == string_quote_char:
                pop_state()
                i += 1
            else:
                i += 1
            continue
            
        # Check for comments
        if char == "/" and i + 1 < n:
            if content[i+1] == "/":
                state_stack.append("COMMENT_LINE")
                i += 2
                continue
            elif content[i+1] == "*":
                state_stack.append("COMMENT_BLOCK")
                i += 2
                continue
                
        if curr_state == "JS":
            if char in ("'", '"', "`"):
                string_quote_char = char
                state_stack.append("STRING")
                i += 1
                continue
                
            if is_tag_start(i):
                state_stack.append("TAG")
                tag_start_idx = i
                tag_braces_depth = 0
                is_closing_tag = (content[i+1] == "/")
                i += 1
                continue
                
            i += 1
            
        elif curr_state == "TAG":
            if char in ("'", '"'):
                string_quote_char = char
                state_stack.append("STRING")
                i += 1
                continue
                
            if char == "{":
                tag_braces_depth += 1
                i += 1
                continue
            elif char == "}":
                tag_braces_depth = max(0, tag_braces_depth - 1)
                i += 1
                continue
                
            if char == ">" and tag_braces_depth == 0:
                is_self_closing = (i > 0 and content[i-1] == "/" and not is_closing_tag)
                pop_state() # pop "TAG"
                
                # Analyze attributes in the tag
                tag_content = content[tag_start_idx:i+1]
                attr_matches = re.finditer(r'(\b[a-zA-Z0-9_-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', tag_content)
                for am in attr_matches:
                    attr_name = am.group(1)
                    attr_val = am.group(2) or am.group(3) or ""
                    if attr_name in TEXT_ATTRIBUTES and has_hardcoded_text(attr_val):
                        line = get_line_number(content, tag_start_idx + am.start())
                        warnings.append({
                            "line": line,
                            "type": "Hardcoded JSX Attribute",
                            "detail": f"Attribute '{attr_name}' has hardcoded user-facing text: \"{attr_val}\""
                        })
                        
                if not is_self_closing:
                    if is_closing_tag:
                        if state_stack[-1] == "JSX":
                            pop_state()
                    else:
                        state_stack.append("JSX")
                        current_jsx_text = []
                        current_jsx_text_start = i + 1
                i += 1
                continue
                
            i += 1
            
        elif curr_state == "JSX":
            if char == "{":
                text_str = "".join(current_jsx_text)
                if has_hardcoded_text(text_str):
                    warnings.append({
                        "line": get_line_number(content, current_jsx_text_start),
                        "type": "Hardcoded JSX Text",
                        "detail": f"Hardcoded user-facing text: \"{text_str.strip()}\""
                    })
                state_stack.append("JSX_JS")
                jsx_braces_depths.append(1)
                i += 1
                continue
                
            if is_tag_start(i):
                text_str = "".join(current_jsx_text)
                if has_hardcoded_text(text_str):
                    warnings.append({
                        "line": get_line_number(content, current_jsx_text_start),
                        "type": "Hardcoded JSX Text",
                        "detail": f"Hardcoded user-facing text: \"{text_str.strip()}\""
                    })
                state_stack.append("TAG")
                tag_start_idx = i
                tag_braces_depth = 0
                is_closing_tag = (content[i+1] == "/")
                i += 1
                continue
                
            current_jsx_text.append(char)
            i += 1
            
        elif curr_state == "JSX_JS":
            if char in ("'", '"', "`"):
                string_quote_char = char
                state_stack.append("STRING")
                i += 1
                continue
                
            if char == "{":
                if jsx_braces_depths:
                    jsx_braces_depths[-1] += 1
                i += 1
                continue
            elif char == "}":
                if jsx_braces_depths:
                    jsx_braces_depths[-1] -= 1
                    if jsx_braces_depths[-1] == 0:
                        jsx_braces_depths.pop()
                        pop_state() # pop "JSX_JS"
                        current_jsx_text = []
                        current_jsx_text_start = i + 1
                i += 1
                continue
                
            if is_tag_start(i):
                state_stack.append("TAG")
                tag_start_idx = i
                tag_braces_depth = 0
                is_closing_tag = (content[i+1] == "/")
                i += 1
                continue
                
            i += 1

    return warnings

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    frontend_dir = os.path.abspath(os.path.join(script_dir, ".."))
    
    en_keys, bg_keys = load_translations(frontend_dir)
    print(f"Loaded {len(en_keys)} English keys, {len(bg_keys)} Bulgarian keys.\n")
    
    src_dir = os.path.join(frontend_dir, "src")
    if not os.path.exists(src_dir):
        print(f"Error: src folder not found at {src_dir}")
        sys.exit(1)
        
    all_warnings = {}
    scanned_count = 0
    
    for root, _, files in os.walk(src_dir):
        for file in files:
            if file.endswith((".jsx", ".js")) and not file.endswith((".test.jsx", ".test.js")) and file != "setupTests.js":
                filepath = os.path.join(root, file)
                rel_path = os.path.relpath(filepath, src_dir)
                scanned_count += 1
                
                try:
                    warnings = analyze_file(filepath, en_keys, bg_keys)
                    if warnings:
                        all_warnings[rel_path] = warnings
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    print(f"Error reading file {rel_path}: {e}")
                    
    print(f"Scanned {scanned_count} files.")
    
    if not all_warnings:
        print("\n\033[92m✔ Clean! No hardcoded texts or missing translation keys found.\033[0m")
        sys.exit(0)
        
    total_warnings = sum(len(w) for w in all_warnings.values())
    print(f"\n\033[91mFound {total_warnings} warnings across {len(all_warnings)} files:\033[0m\n")
    
    for rel_path, warnings in sorted(all_warnings.items()):
        print(f"\033[93m[src/{rel_path}]\033[0m")
        for w in sorted(warnings, key=lambda x: x["line"]):
            print(f"  Line {w['line']}: \033[1m{w['type']}\033[0m - {w['detail']}")
        print()
        
    sys.exit(1)

if __name__ == "__main__":
    main()
