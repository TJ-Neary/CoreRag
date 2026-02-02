#!/usr/bin/env bash
# =============================================================================
# CoreRag Pre-Commit Security Scanner
# =============================================================================
# Scans tracked (or staged) files for secrets, PII, hardcoded paths, and other
# data that should never be committed to a public repository.
#
# Usage:
#   ./scripts/security_scan.sh              # Scan all tracked files
#   ./scripts/security_scan.sh --staged     # Scan only staged changes (for pre-commit hook)
#   ./scripts/security_scan.sh --fix        # Show suggested fixes
#
# Exit codes:
#   0 = clean
#   1 = findings detected
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

FINDINGS=0
MODE="tracked"  # "tracked" or "staged"
SHOW_FIX=false

for arg in "$@"; do
    case $arg in
        --staged) MODE="staged" ;;
        --fix)    SHOW_FIX=true ;;
        --help|-h)
            echo "Usage: $0 [--staged] [--fix]"
            echo "  --staged  Scan only staged changes (for pre-commit hook)"
            echo "  --fix     Show suggested fixes for each finding"
            exit 0
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
finding() {
    local severity="$1"  # CRITICAL, HIGH, MEDIUM, LOW
    local category="$2"
    local file="$3"
    local detail="$4"
    local fix="${5:-}"

    FINDINGS=$((FINDINGS + 1))

    case "$severity" in
        CRITICAL) color="$RED" ;;
        HIGH)     color="$RED" ;;
        MEDIUM)   color="$YELLOW" ;;
        LOW)      color="$CYAN" ;;
        *)        color="$NC" ;;
    esac

    echo -e "${color}[${severity}]${NC} ${BOLD}${category}${NC}"
    echo -e "  File: ${file}"
    echo -e "  Detail: ${detail}"
    if [ "$SHOW_FIX" = true ] && [ -n "$fix" ]; then
        echo -e "  ${GREEN}Fix: ${fix}${NC}"
    fi
    echo ""
}

get_files() {
    if [ "$MODE" = "staged" ]; then
        git diff --cached --name-only --diff-filter=ACMR 2>/dev/null || true
    else
        git ls-files 2>/dev/null || true
    fi
}

get_content() {
    if [ "$MODE" = "staged" ]; then
        git diff --cached -U0 2>/dev/null || true
    else
        # Search tracked file contents
        cat "$1" 2>/dev/null || true
    fi
}

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}========================================${NC}"
echo -e "${BOLD} CoreRag Security Scanner${NC}"
echo -e "${BOLD}========================================${NC}"
echo -e " Mode: ${CYAN}${MODE}${NC}"
echo -e " Date: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# ---------------------------------------------------------------------------
# 1. API Keys & Secrets
# ---------------------------------------------------------------------------
echo -e "${BOLD}[1/7] Scanning for API keys and secrets...${NC}"

# Common secret patterns (applied to file contents)
SECRET_PATTERNS=(
    'sk-[a-zA-Z0-9]{20,}'                           # OpenAI keys
    'sk-proj-[a-zA-Z0-9]{20,}'                      # OpenAI project keys
    'AKIA[0-9A-Z]{16}'                               # AWS access key IDs
    'ghp_[a-zA-Z0-9]{36}'                            # GitHub personal tokens
    'gho_[a-zA-Z0-9]{36}'                            # GitHub OAuth tokens
    'github_pat_[a-zA-Z0-9_]{22,}'                   # GitHub fine-grained tokens
    'xox[bsp]-[a-zA-Z0-9\-]{10,}'                   # Slack tokens
    'AIza[0-9A-Za-z\-_]{35}'                         # Google API keys
    'ya29\.[0-9A-Za-z\-_]+'                          # Google OAuth tokens
    'GOCSPX-[a-zA-Z0-9\-_]+'                        # Google client secrets
    'eyJ[a-zA-Z0-9_-]*\.eyJ[a-zA-Z0-9_-]*\.'       # JWT tokens
    'ssh-rsa\s+AAAA'                                 # SSH private keys
    'BEGIN (RSA |DSA |EC )?PRIVATE KEY'              # PEM private keys
    'BEGIN CERTIFICATE'                               # Certificates
    'password\s*=\s*["\x27][^"\x27]{8,}["\x27]'     # Hardcoded passwords
    'secret\s*=\s*["\x27][^"\x27]{8,}["\x27]'       # Hardcoded secrets
    'token\s*=\s*["\x27][^"\x27]{20,}["\x27]'       # Hardcoded tokens
)

while IFS= read -r file; do
    # Skip binary files and non-text
    [[ "$file" =~ \.(png|jpg|jpeg|gif|ico|woff|ttf|eot|svg|pyc|so|db|sqlite)$ ]] && continue
    [ ! -f "$file" ] && continue
    # Skip test fixtures (contain intentional synthetic secrets for PII detection testing)
    [[ "$file" =~ ^tests/ ]] && continue
    # Skip PII detection module (contains regex patterns for *detecting* secrets, not actual secrets)
    [[ "$file" =~ privacy_audit\.py$ ]] && continue
    # Skip this script itself (contains the patterns it scans for)
    [[ "$file" =~ security_scan\.sh$ ]] && continue

    for pattern in "${SECRET_PATTERNS[@]}"; do
        matches=$(grep -nEi "$pattern" "$file" 2>/dev/null | head -5 || true)
        if [ -n "$matches" ]; then
            # Filter out example/template files and comments about patterns
            if ! echo "$matches" | grep -qiE '(example|template|placeholder|your-key-here|your.key|CHANGE_ME)'; then
                finding "CRITICAL" "Secret/API Key" "$file" \
                    "Possible secret matching pattern: ${pattern:0:40}..." \
                    "Move to .env (gitignored) and load via os.getenv()"
            fi
        fi
    done
done < <(get_files)

# ---------------------------------------------------------------------------
# 2. Hardcoded User Paths
# ---------------------------------------------------------------------------
echo -e "${BOLD}[2/7] Scanning for hardcoded user paths...${NC}"

while IFS= read -r file; do
    [[ "$file" =~ \.(png|jpg|jpeg|gif|ico|woff|ttf|eot|svg|pyc|so|db|sqlite)$ ]] && continue
    [ ! -f "$file" ] && continue

    # Match /Users/<real-username> but not documentation placeholders or synthetic test users
    matches=$(grep -nE '/Users/[a-z][a-z0-9_.-]+/' "$file" 2>/dev/null \
        | grep -vE '(/Users/yourname/|/Users/user/|/Users/test/|\$HOME|Path\.home|os\.path\.expanduser|SCRIPT_DIR|example|placeholder)' \
        | head -5 || true)

    if [ -n "$matches" ]; then
        finding "HIGH" "Hardcoded User Path" "$file" \
            "$(echo "$matches" | head -1)" \
            "Use Path.home(), \$HOME, or SCRIPT_DIR instead of absolute user paths"
    fi
done < <(get_files)

# ---------------------------------------------------------------------------
# 3. PII Patterns (names, emails, SSNs, phone numbers)
# ---------------------------------------------------------------------------
echo -e "${BOLD}[3/7] Scanning for PII patterns...${NC}"

while IFS= read -r file; do
    [[ "$file" =~ \.(png|jpg|jpeg|gif|ico|woff|ttf|eot|svg|pyc|so|db|sqlite)$ ]] && continue
    [ ! -f "$file" ] && continue

    # Skip test fixtures that intentionally use synthetic PII
    [[ "$file" =~ ^tests/ ]] && continue
    # Skip this script itself
    [[ "$file" =~ security_scan\.sh$ ]] && continue
    # Skip files that contain instructional examples, not real PII
    [[ "$file" =~ pii_terms\.example ]] && continue
    [[ "$file" =~ SECURITY\.md$ ]] && continue
    [[ "$file" =~ \.security_terms\.example$ ]] && continue

    # Real SSN pattern (not documentation about SSN patterns)
    matches=$(grep -nE '\b[0-9]{3}-[0-9]{2}-[0-9]{4}\b' "$file" 2>/dev/null \
        | grep -vE '(example|123-45-6789|000-00-0000|XXX-XX-XXXX|regex|pattern|detect|format|test)' \
        | head -3 || true)
    if [ -n "$matches" ]; then
        finding "CRITICAL" "Possible SSN" "$file" \
            "$(echo "$matches" | head -1)" \
            "Remove or replace with placeholder (XXX-XX-XXXX)"
    fi

    # Real email addresses (not generic/example ones)
    matches=$(grep -nEio '\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b' "$file" 2>/dev/null \
        | grep -viE '(example\.com|example\.org|test\.com|noreply@|placeholder|user@|john\.doe|jane\.doe|foo@bar)' \
        | head -3 || true)
    if [ -n "$matches" ]; then
        finding "HIGH" "Real Email Address" "$file" \
            "$(echo "$matches" | head -1)" \
            "Replace with user@example.com or similar placeholder"
    fi

    # US phone numbers (not in documentation context)
    matches=$(grep -nE '\b(\+1[-.]?)?\(?[0-9]{3}\)?[-. ][0-9]{3}[-. ][0-9]{4}\b' "$file" 2>/dev/null \
        | grep -vE '(example|555-|000-|123-456|format|regex|pattern|detect|test)' \
        | head -3 || true)
    if [ -n "$matches" ]; then
        finding "MEDIUM" "Possible Phone Number" "$file" \
            "$(echo "$matches" | head -1)" \
            "Replace with (555) 555-0100 or similar placeholder"
    fi

    # Credit card patterns (basic check)
    matches=$(grep -nE '\b[0-9]{4}[- ]?[0-9]{4}[- ]?[0-9]{4}[- ]?[0-9]{4}\b' "$file" 2>/dev/null \
        | grep -vE '(example|0000|1234|test|pattern|regex|detect|format|xxxx)' \
        | head -3 || true)
    if [ -n "$matches" ]; then
        finding "CRITICAL" "Possible Credit Card" "$file" \
            "$(echo "$matches" | head -1)" \
            "Remove immediately"
    fi
done < <(get_files)

# ---------------------------------------------------------------------------
# 4. Internal Project References (names of private projects, employers, etc.)
# ---------------------------------------------------------------------------
echo -e "${BOLD}[4/7] Scanning for internal/private references...${NC}"

# Check for references to private project names that shouldn't be public.
# Add project-specific terms here as needed.
PRIVATE_TERMS_FILE="$PROJECT_ROOT/.security_terms"

if [ -f "$PRIVATE_TERMS_FILE" ]; then
    while IFS= read -r term; do
        # Skip empty lines and comments
        [[ -z "$term" || "$term" =~ ^# ]] && continue

        while IFS= read -r file; do
            [[ "$file" =~ \.(png|jpg|jpeg|gif|ico|woff|ttf|eot|svg|pyc|so|db|sqlite)$ ]] && continue
            [ ! -f "$file" ] && continue
            # Skip gitignored files and this script
            [[ "$file" =~ security_scan\.sh$ ]] && continue
            [[ "$file" =~ \.security_terms$ ]] && continue

            matches=$(grep -niF "$term" "$file" 2>/dev/null | head -3 || true)
            if [ -n "$matches" ]; then
                finding "HIGH" "Private Reference" "$file" \
                    "Contains private term '${term}'" \
                    "Replace with generic language or move file to gitignored location"
            fi
        done < <(get_files)
    done < "$PRIVATE_TERMS_FILE"
else
    echo -e "  ${YELLOW}No .security_terms file found. Create one to scan for private names/terms.${NC}"
    echo -e "  ${YELLOW}Format: one term per line (e.g., employer names, private project names).${NC}"
    echo ""
fi

# ---------------------------------------------------------------------------
# 5. .env / Config Files That Should Be Gitignored
# ---------------------------------------------------------------------------
echo -e "${BOLD}[5/7] Checking for sensitive files that should be gitignored...${NC}"

SENSITIVE_FILES=(
    ".env"
    ".env.local"
    ".env.production"
    "secrets.json"
    "credentials.json"
    "pii_terms.yaml"
    "pii_terms.yml"
    "sorting_rules.yaml"
    "sorting_rules.yml"
    "staging_manifest.json"
)

while IFS= read -r file; do
    basename=$(basename "$file")
    for sensitive in "${SENSITIVE_FILES[@]}"; do
        if [ "$basename" = "$sensitive" ]; then
            finding "CRITICAL" "Sensitive File Tracked" "$file" \
                "This file should be gitignored, not committed" \
                "Run: git rm --cached '$file' && add to .gitignore"
        fi
    done
done < <(get_files)

# ---------------------------------------------------------------------------
# 6. Database / Binary Files That Shouldn't Be Committed
# ---------------------------------------------------------------------------
echo -e "${BOLD}[6/7] Checking for database and binary files...${NC}"

while IFS= read -r file; do
    case "$file" in
        *.db|*.sqlite|*.sqlite3)
            finding "HIGH" "Database File Tracked" "$file" \
                "Database files contain runtime data and shouldn't be committed" \
                "Add to .gitignore and run: git rm --cached '$file'"
            ;;
        *.lance|*.lancedb)
            finding "HIGH" "Vector DB File Tracked" "$file" \
                "LanceDB files contain indexed content and shouldn't be committed" \
                "Add to .gitignore and run: git rm --cached '$file'"
            ;;
        *.log)
            finding "MEDIUM" "Log File Tracked" "$file" \
                "Log files may contain PII or sensitive runtime data" \
                "Add to .gitignore and run: git rm --cached '$file'"
            ;;
    esac
done < <(get_files)

# ---------------------------------------------------------------------------
# 7. Dangerous Code Patterns
# ---------------------------------------------------------------------------
echo -e "${BOLD}[7/7] Scanning for dangerous code patterns...${NC}"

while IFS= read -r file; do
    [[ "$file" =~ \.(py)$ ]] || continue
    [ ! -f "$file" ] && continue
    # Skip this being flagged in SECURITY.md or docs
    [[ "$file" =~ (SECURITY|security_scan) ]] && continue

    # shell=True with variable input
    matches=$(grep -nE 'subprocess\.(run|call|Popen).*shell\s*=\s*True' "$file" 2>/dev/null | head -3 || true)
    if [ -n "$matches" ]; then
        finding "HIGH" "Shell Injection Risk" "$file" \
            "$(echo "$matches" | head -1)" \
            "Use subprocess.run([...]) with list args instead of shell=True"
    fi

    # verify=False on HTTPS requests
    matches=$(grep -nE 'verify\s*=\s*False' "$file" 2>/dev/null | head -3 || true)
    if [ -n "$matches" ]; then
        finding "MEDIUM" "SSL Verification Disabled" "$file" \
            "$(echo "$matches" | head -1)" \
            "Remove verify=False to enable certificate verification"
    fi

    # Binding to 0.0.0.0 (network-accessible)
    matches=$(grep -nE '(host\s*=\s*["\x27]0\.0\.0\.0|0\.0\.0\.0.*bind)' "$file" 2>/dev/null | head -3 || true)
    if [ -n "$matches" ]; then
        finding "MEDIUM" "Network-Exposed Server" "$file" \
            "$(echo "$matches" | head -1)" \
            "Bind to 127.0.0.1 for local-only access"
    fi

    # eval() or exec() with variables
    matches=$(grep -nE '\b(eval|exec)\s*\(' "$file" 2>/dev/null \
        | grep -vE '(#|comment|test|example)' \
        | head -3 || true)
    if [ -n "$matches" ]; then
        finding "HIGH" "Dynamic Code Execution" "$file" \
            "$(echo "$matches" | head -1)" \
            "Avoid eval()/exec() — use safer alternatives"
    fi
done < <(get_files)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo -e "${BOLD}========================================${NC}"
if [ "$FINDINGS" -eq 0 ]; then
    echo -e "${GREEN}${BOLD} CLEAN — No security findings detected${NC}"
    echo -e "${BOLD}========================================${NC}"
    echo ""
    exit 0
else
    echo -e "${RED}${BOLD} FOUND ${FINDINGS} ISSUE(S)${NC}"
    echo -e "${BOLD}========================================${NC}"
    echo ""
    echo -e "Run with ${CYAN}--fix${NC} flag to see suggested remediation."
    echo -e "See ${CYAN}SECURITY.md${NC} for full security guidelines."
    echo ""
    exit 1
fi
