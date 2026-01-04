#!/usr/bin/env python3
"""
Test prompts for intelligent path shortening using full context.
"""

import subprocess
import json

# Real examples from the books directory with expected outputs
TEST_CASES = [
    {
        "input": r"books\1984 (George Orwell) - Audio Book\Audio Books - George Orwell - 1984 - 1 of 14.mp3",
        "expected": "books/1984/01.mp3",
        "notes": "Simple: author in dir, title redundant"
    },
    {
        "input": r"books\Aldous Huxley's - Brave New World\Brave New World - 01 of 10.mp3",
        "expected": "books/Brave New World/01.mp3",
        "notes": "Keep title, drop author from dir"
    },
    {
        "input": r"books\Harry Potter (Jim Dale)\(1997) Harry Potter And The Philosopher's Stone\Chapter 01 - The Boy Who Lived.mp3",
        "expected": "books/Harry Potter/1997 - HP & Philosopher's Stone/01.mp3",
        "notes": "Series/Book/Track with year and abbreviation"
    },
    {
        "input": r"books\The Hobbit Audiobook\The Hobbit (Disc 01)\1-01 Ch 1a, An Unexpected Party.mp3",
        "expected": "books/Hobbit/1-01.mp3",
        "notes": "Flatten discs, keep disc-track number"
    },
    {
        "input": r"books\Roald Dahl Audiobooks\Roald Dahl - Charlie and the Chocolate Factory\(Roald Dahl) Charlie and the Chocolate Factory (Part 1) - 01.mp3",
        "expected": "books/Roald Dahl/Charlie & Chocolate Factory/1-01.mp3",
        "notes": "Author/Book/Part-Track"
    },
    {
        "input": r"books\Roald Dahl Audiobooks\Roald Dahl - Charlie and the Chocolate Factory\(Roald Dahl) Charlie and the Chocolate Factory (Part 3) - 10.mp3",
        "expected": "books/Roald Dahl/Charlie & Chocolate Factory/3-10.mp3",
        "notes": "Same book, different part"
    },
    {
        "input": r"books\William Gibson-Collection\William Gibson-Blue Ant Trilogy[1-3]\William Gibson-Blue Ant Trilogy-#1-Pattern Recognition\Pattern Recognition - 001.mp3",
        "expected": "books/William Gibson/Blue Ant Trilogy/Pattern Recognition/001.mp3",
        "notes": "Author/Series/Book/Track"
    },
    {
        "input": r"books\Harry Potter (Jim Dale)\(1998) Harry Potter And The Chamber Of Secrets\Chapter 01 - The Worst Birthday.mp3",
        "expected": "books/Harry Potter/1998 - HP & Chamber of Secrets/01.mp3",
        "notes": "Series with different year - test consistency"
    },
    {
        "input": r"books\Gulliver's Travels\01 Voyage to Liliput.mp3",
        "expected": "books/Gulliver's Travels/01.mp3",
        "notes": "Already simple, just drop chapter title"
    },
    {
        "input": r"books\1984 (George Orwell) - Audio Book\Audio Books - George Orwell - 1984 - 14 of 14.mp3",
        "expected": "books/1984/14.mp3",
        "notes": "Double-digit track number"
    },
]

PROMPTS = {
    "v7_refined": """Shorten audiobook path. Remove redundancy, keep hierarchy. Extract part/disc into filename.

Examples:
books\\1984 (George Orwell) - Audio Book\\Audio Books - George Orwell - 1984 - 1 of 14.mp3
→ books/1984/01.mp3

books\\Aldous Huxley's - Brave New World\\Brave New World - 01 of 10.mp3
→ books/Brave New World/01.mp3

books\\Harry Potter (Jim Dale)\\(1997) Harry Potter And The Philosopher's Stone\\Chapter 01 - The Boy Who Lived.mp3
→ books/Harry Potter/1997 - HP & Philosopher's Stone/01.mp3

books\\Harry Potter (Jim Dale)\\(1998) Harry Potter And The Chamber Of Secrets\\Chapter 01 - The Worst Birthday.mp3
→ books/Harry Potter/1998 - HP & Chamber of Secrets/01.mp3

books\\The Hobbit Audiobook\\The Hobbit (Disc 01)\\1-01 Ch 1a, An Unexpected Party.mp3
→ books/Hobbit/1-01.mp3

books\\Roald Dahl Audiobooks\\Roald Dahl - Charlie and the Chocolate Factory\\(Roald Dahl) Charlie and the Chocolate Factory (Part 1) - 01.mp3
→ books/Roald Dahl/Charlie & Chocolate Factory/1-01.mp3

books\\Roald Dahl Audiobooks\\Roald Dahl - Charlie and the Chocolate Factory\\(Roald Dahl) Charlie and the Chocolate Factory (Part 3) - 10.mp3
→ books/Roald Dahl/Charlie & Chocolate Factory/3-10.mp3

books\\William Gibson-Collection\\William Gibson-Blue Ant Trilogy[1-3]\\William Gibson-Blue Ant Trilogy-#1-Pattern Recognition\\Pattern Recognition - 001.mp3
→ books/William Gibson/Blue Ant Trilogy/Pattern Recognition/001.mp3

books\\Gulliver's Travels\\01 Voyage to Liliput.mp3
→ books/Gulliver's Travels/01.mp3

Rules:
- Extract "Part N" or "Disc N" from filename → format as N-tracknum.mp3
- Remove "#1", "[1-3]" etc from directories
- Replace "and"/"And" with "&"
- Drop "Audiobook", "Audio Book", "Collection"
- Remove "The" from start of single book titles (keep for series like "The Hobbit" if standalone)
- Keep years in parentheses for series (e.g., 1997, 1998)
- Abbreviate long book titles in series

Path: {path}
Output (path only, no markdown, no explanation):""",

    "v6_improved": """Shorten audiobook path. Remove redundancy, keep hierarchy. Extract part/disc numbers into filename.

Examples:
books\\1984 (George Orwell) - Audio Book\\Audio Books - George Orwell - 1984 - 1 of 14.mp3
→ books/1984/01.mp3

books\\Harry Potter (Jim Dale)\\(1997) Harry Potter And The Philosopher's Stone\\Chapter 01 - The Boy Who Lived.mp3
→ books/Harry Potter/1997 - HP & Philosopher's Stone/01.mp3

books\\The Hobbit Audiobook\\The Hobbit (Disc 01)\\1-01 Ch 1a, An Unexpected Party.mp3
→ books/Hobbit/1-01.mp3

books\\Roald Dahl Audiobooks\\Roald Dahl - Charlie and the Chocolate Factory\\(Roald Dahl) Charlie and the Chocolate Factory (Part 1) - 01.mp3
→ books/Roald Dahl/Charlie & Chocolate Factory/1-01.mp3

books\\William Gibson-Collection\\William Gibson-Blue Ant Trilogy[1-3]\\William Gibson-Blue Ant Trilogy-#1-Pattern Recognition\\Pattern Recognition - 001.mp3
→ books/William Gibson/Blue Ant Trilogy/Pattern Recognition/001.mp3

Key rules:
- If filename has "Part N" or similar, extract N and format as N-tracknum.mp3
- Remove book/series numbers from path (like "#1", "[1-3]"), keep only in filename if it's the track number
- Use "&" instead of "and" in titles
- Drop words like "Audiobook", "Audio Book", "Collection"

Path: {path}
Shortened (path only):""",

    "v1_contextual": """You are an audiobook path optimizer. Given a full file path, create the SHORTEST meaningful path that preserves essential information.

Rules:
- Understand the hierarchy: Author → Series → Book → Disc/Part → Track
- Remove redundant information (e.g., "Audio Book", author names repeated in filenames)
- Keep what matters: series names, book titles (abbreviated if long), track numbers
- Use abbreviations for long titles (e.g., "Harry Potter & Philosopher's Stone" → "HP & Philosopher's Stone")
- Use "&" instead of "and"
- Preserve part/disc numbers in the filename (e.g., "1-01" for disc 1, track 01)
- Always use forward slashes (/)
- Keep track numbers with appropriate padding (01, 001, etc.)

Examples:
Input: books\\1984 (George Orwell) - Audio Book\\Audio Books - George Orwell - 1984 - 1 of 14.mp3
Output: books/1984/01.mp3

Input: books\\Harry Potter (Jim Dale)\\(1997) Harry Potter And The Philosopher's Stone\\Chapter 01 - The Boy Who Lived.mp3
Output: books/Harry Potter/1997 - HP & Philosopher's Stone/01.mp3

Input: books\\Roald Dahl Audiobooks\\Roald Dahl - Charlie and the Chocolate Factory\\(Roald Dahl) Charlie and the Chocolate Factory (Part 1) - 01.mp3
Output: books/Roald Dahl/Charlie & Chocolate Factory/1-01.mp3

Now optimize this path (respond with ONLY the new path):
{path}""",

    "v2_structured": """Task: Optimize audiobook file path to minimal meaningful form

Input path: {path}

Instructions:
1. Analyze the directory structure and filename
2. Identify: base_dir / author_or_series / book / part_or_disc / track
3. Remove redundancy (repeated names, "Audio Book", etc.)
4. Abbreviate long titles, use "&" instead of "and"
5. Format track numbers: NN.mp3 or D-NN.mp3 (disc-track)
6. Use forward slashes

Output (path only):""",

    "v3_json": """Optimize this audiobook path to be minimal but meaningful.

Path: {path}

Context awareness:
- Directory names often contain author/series info
- Filenames often repeat this info unnecessarily
- Multi-disc books may have disc numbers in path or filename
- Track numbers should be preserved with padding

Optimization goals:
- Remove redundant text
- Keep essential hierarchy (series → book → track)
- Abbreviate long titles
- Use "&" for "and"
- Format: books/Author or Series/Book (if needed)/track.mp3

Respond with JSON: {{"optimized_path": "..."}}""",

    "v4_minimal_examples": """Shorten audiobook path. Remove redundancy, keep hierarchy.

Examples:
books\\1984 (George Orwell) - Audio Book\\Audio Books - George Orwell - 1984 - 1 of 14.mp3
→ books/1984/01.mp3

books\\Harry Potter (Jim Dale)\\(1997) Harry Potter And The Philosopher's Stone\\Chapter 01 - The Boy Who Lived.mp3
→ books/Harry Potter/1997 - HP & Philosopher's Stone/01.mp3

books\\The Hobbit Audiobook\\The Hobbit (Disc 01)\\1-01 Ch 1a, An Unexpected Party.mp3
→ books/Hobbit/1-01.mp3

Path: {path}
Shortened (path only):""",

    "v5_step_by_step": """Optimize this audiobook path by following these steps:

1. Parse the path to identify: base / author_or_series / book_title / disc_or_part / filename
2. Extract the track number from filename (preserve disc/part if present)
3. Simplify directory names:
   - Remove words like "Audio Book", "Audiobook", "Collection"
   - Remove author name if it's repeated in subdirectories
   - Abbreviate long book titles (keep first letters of main words)
   - Replace "and" with "&"
4. Build minimal path: base/author_or_series/book/track.mp3

Input: {path}

Think through it, then output ONLY the final path:""",
}


def test_prompt(prompt_name, prompt_template, test_case):
    """Test a prompt against a test case."""
    path = test_case["input"]
    expected = test_case["expected"]

    prompt = prompt_template.format(path=path)

    print(f"\n{'='*80}")
    print(f"Prompt: {prompt_name}")
    print(f"Input:    {path}")
    print(f"Expected: {expected}")
    print(f"{'='*80}")

    try:
        result = subprocess.run(
            ['claude', '--print', prompt],
            capture_output=True,
            text=True,
            timeout=30
        )

        output = result.stdout.strip()

        # Try to extract just the path from the output
        lines = [line.strip() for line in output.split('\n') if line.strip()]

        # Handle JSON responses
        if prompt_name == "v3_json":
            try:
                json_data = json.loads(output)
                clean_output = json_data.get("optimized_path", output)
            except:
                # Try to find JSON in the output
                for line in lines:
                    if line.startswith('{'):
                        try:
                            json_data = json.loads(line)
                            clean_output = json_data.get("optimized_path", line)
                            break
                        except:
                            clean_output = lines[-1] if lines else output
                else:
                    clean_output = lines[-1] if lines else output
        else:
            # For non-JSON, take the last line that looks like a path
            clean_output = None
            for line in reversed(lines):
                if 'books/' in line.lower() and '.mp3' in line.lower():
                    clean_output = line
                    break
            if not clean_output:
                clean_output = lines[-1] if lines else output

        # Remove any markdown formatting
        clean_output = clean_output.replace('`', '').strip()

        print(f"Got:      {clean_output}")

        # Check if it matches expected
        match = clean_output == expected
        print(f"Match:    {'YES' if match else 'NO'}")

        return clean_output, match

    except subprocess.TimeoutExpired:
        print("ERROR: Timeout")
        return None, False
    except Exception as e:
        print(f"ERROR: {e}")
        return None, False


def run_all_tests():
    """Run all prompts against all test cases."""
    results = {}

    for prompt_name, prompt_template in PROMPTS.items():
        print(f"\n\n{'#'*80}")
        print(f"# TESTING PROMPT: {prompt_name}")
        print(f"{'#'*80}")

        results[prompt_name] = {
            'outputs': [],
            'matches': 0,
            'total': 0
        }

        for test_case in TEST_CASES:
            output, match = test_prompt(prompt_name, prompt_template, test_case)
            results[prompt_name]['outputs'].append({
                'input': test_case['input'],
                'expected': test_case['expected'],
                'got': output,
                'match': match
            })
            results[prompt_name]['total'] += 1
            if match:
                results[prompt_name]['matches'] += 1

    # Print summary
    print(f"\n\n{'='*80}")
    print("SUMMARY - MATCH RATES")
    print(f"{'='*80}\n")

    for prompt_name, data in results.items():
        match_rate = (data['matches'] / data['total'] * 100) if data['total'] > 0 else 0
        print(f"{prompt_name:25} {data['matches']}/{data['total']} ({match_rate:.1f}%)")

    # Show mismatches
    print(f"\n\n{'='*80}")
    print("MISMATCHES DETAILS")
    print(f"{'='*80}\n")

    for prompt_name, data in results.items():
        mismatches = [item for item in data['outputs'] if not item['match']]
        if mismatches:
            print(f"\n{prompt_name}:")
            for item in mismatches:
                print(f"  Input:    {item['input'][:60]}...")
                print(f"  Expected: {item['expected']}")
                print(f"  Got:      {item['got']}")
                print()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # Test specific prompt
        prompt_name = sys.argv[1]
        if prompt_name in PROMPTS:
            for test_case in TEST_CASES:
                test_prompt(prompt_name, PROMPTS[prompt_name], test_case)
        else:
            print(f"Unknown prompt: {prompt_name}")
            print(f"Available: {', '.join(PROMPTS.keys())}")
    else:
        run_all_tests()
