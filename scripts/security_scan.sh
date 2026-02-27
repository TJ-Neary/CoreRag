#!/usr/bin/env bash
# =============================================================================
# _HQ Pre-Commit Security Scanner — v7
# =============================================================================
# Consolidated scanner combining the best of shell (v4) and Python audit
# capabilities. This is the canonical version — all projects should use this.
#
# Usage:
#   ./scripts/security_scan.sh              # Scan all tracked files
#   ./scripts/security_scan.sh --staged     # Scan only staged changes (pre-commit)
#   ./scripts/security_scan.sh --fix        # Show suggested fixes
#   ./scripts/security_scan.sh --version    # Print version
#
# Exit codes:
#   0 = clean (acknowledged findings don't count)
#   1 = findings detected
#
# Suppression:
#   - Per-file baseline:  .security_baseline (category|glob|reason)
#   - Per-line inline:    # nosec
#   - Private terms:      .security_terms (one term per line)
#
# Changelog:
#   v7 — Ecosystem reference check phase (14/14). Detects _HQ, hq-coord,
#         cross-project imports, and localhost port references in source files.
#         Informational for private repos, review-required for public repos.
#   v6 — GitHub ToS compliance phase (13/13). Scans for sexually obscene content,
#         violence/threats, harassment, malware distribution, CSAM references,
#         privacy violations, license bypass tools, and AI safety bypass language.
#         Also adds .tos_terms support for project-specific prohibited content.
#   v5 — Merged Python audit_security.py strengths: .gitignore compliance,
#         .env.example parity, .env KEY=VALUE scanning, YAML secret values,
#         # nosec inline suppression. Baseline system now in template.
#   v4 — Commercial/sensitivity markers, private asset visibility.
#   v3 — Baseline system, severity levels.
#   v2 — Initial 7-check scanner.
# =============================================================================

set -euo pipefail

# Scanner version — bump when checks change. Used by /commit to detect outdated scanners.
SCANNER_VERSION="6"

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
DIM='\033[2m'
NC='\033[0m' # No Color

FINDINGS=0
ACKNOWLEDGED=0
MODE="tracked"  # "tracked" or "staged"
SHOW_FIX=false

for arg in "$@"; do
    case $arg in
        --staged) MODE="staged" ;;
        --fix)    SHOW_FIX=true ;;
        --version) echo "security_scan.sh v${SCANNER_VERSION}"; exit 0 ;;
        --help|-h)
            echo "Usage: $0 [--staged] [--fix] [--version]"
            echo "  --staged   Scan only staged changes (for pre-commit hook)"
            echo "  --fix      Show suggested fixes for each finding"
            echo "  --version  Print scanner version"
            exit 0
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Baseline (acknowledged findings — reported but don't fail the scan)
# ---------------------------------------------------------------------------
# Format: one entry per line — "category|file_glob|reason"
# Lines starting with # are comments. Blank lines are skipped.
BASELINE_FILE="$PROJECT_ROOT/.security_baseline"
BASELINE_ENTRIES=()

if [ -f "$BASELINE_FILE" ]; then
    while IFS= read -r line; do
        [[ -z "$line" || "$line" =~ ^# ]] && continue
        BASELINE_ENTRIES+=("$line")
    done < "$BASELINE_FILE"
fi

is_baselined() {
    local category="$1"
    local file="$2"
    [ ${#BASELINE_ENTRIES[@]} -eq 0 ] && return 1
    for entry in "${BASELINE_ENTRIES[@]}"; do
        local bl_category="${entry%%|*}"
        local bl_pattern="${entry#*|}"
        # Strip reason field if present (category|pattern|reason)
        bl_pattern="${bl_pattern%%|*}"
        if [ "$category" = "$bl_category" ]; then
            # shellcheck disable=SC2254
            case "$file" in
                $bl_pattern) return 0 ;;
            esac
        fi
    done
    return 1
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
finding() {
    local severity="$1"  # CRITICAL, HIGH, MEDIUM, LOW
    local category="$2"
    local file="$3"
    local detail="$4"
    local fix="${5:-}"

    # Check if this finding is baselined (acknowledged)
    if is_baselined "$category" "$file"; then
        ACKNOWLEDGED=$((ACKNOWLEDGED + 1))
        echo -e "${DIM}[ACKNOWLEDGED]${NC} ${DIM}${category}${NC}"
        echo -e "  ${DIM}File: ${file}${NC}"
        echo -e "  ${DIM}Detail: ${detail}${NC}"
        echo ""
        return
    fi

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

is_binary() {
    [[ "$1" =~ \.(png|jpg|jpeg|gif|ico|woff|woff2|ttf|eot|svg|pyc|so|db|sqlite|sqlite3|mo|whl|tar|gz|zip|bz2|xz)$ ]]
}

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
PROJECT_NAME=$(basename "$PROJECT_ROOT")
echo ""
echo -e "${BOLD}========================================${NC}"
echo -e "${BOLD} ${PROJECT_NAME} Security Scanner v${SCANNER_VERSION}${NC}"
echo -e "${BOLD}========================================${NC}"
echo -e " Mode: ${CYAN}${MODE}${NC}"
echo -e " Date: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# ===========================================================================
# 1/13. API Keys & Secrets
# ===========================================================================
echo -e "${BOLD}[1/13] Scanning for API keys and secrets...${NC}"

SECRET_PATTERNS=(
    'sk-[a-zA-Z0-9]{20,}'                           # OpenAI keys
    'sk-proj-[a-zA-Z0-9]{20,}'                      # OpenAI project keys
    'sk-ant-[a-zA-Z0-9]{20,}'                       # Anthropic keys
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
    'bearer\s+[a-zA-Z0-9\-_.]{20,}'                  # Bearer tokens in headers
)

while IFS= read -r file; do
    is_binary "$file" && continue
    [ ! -f "$file" ] && continue
    [[ "$file" =~ ^tests/ ]] && continue
    [[ "$file" =~ audit_security\.py$ ]] && continue
    [[ "$file" =~ security_scan\.sh$ ]] && continue

    for pattern in "${SECRET_PATTERNS[@]}"; do
        matches=$(grep -nEi "$pattern" "$file" 2>/dev/null | head -5 || true)
        if [ -n "$matches" ]; then
            # Filter out placeholders, examples, and nosec suppressions
            if ! echo "$matches" | grep -qiE '(example|template|placeholder|your-key-here|your.key|CHANGE_ME|nosec)'; then
                finding "CRITICAL" "Secret/API Key" "$file" \
                    "Possible secret matching pattern: ${pattern:0:40}..." \
                    "Move to .env (gitignored) and load via os.getenv()"
            fi
        fi
    done
done < <(get_files)

# ===========================================================================
# 2/13. YAML Secret Values (from Python audit)
# ===========================================================================
echo -e "${BOLD}[2/13] Scanning YAML files for secret values...${NC}"

YAML_SECRET_PATTERNS=(
    '(api_?key|secret_?key|password|auth_?token|private_?key)\s*:\s*[^\s#\x27"]{8,}'
)

while IFS= read -r file; do
    [[ "$file" =~ \.(yaml|yml)$ ]] || continue
    [ ! -f "$file" ] && continue
    [[ "$file" =~ ^tests/ ]] && continue
    [[ "$file" =~ \.example\. ]] && continue
    [[ "$file" =~ example\.yaml$ ]] && continue

    for pattern in "${YAML_SECRET_PATTERNS[@]}"; do
        matches=$(grep -nEi "$pattern" "$file" 2>/dev/null | head -5 || true)
        if [ -n "$matches" ]; then
            if ! echo "$matches" | grep -qiE '(example|placeholder|your|changeme|localhost|127\.0\.0\.1|nosec)'; then
                finding "HIGH" "YAML Secret Value" "$file" \
                    "$(echo "$matches" | head -1)" \
                    "Move secret to .env and reference via env var"
            fi
        fi
    done
done < <(get_files)

# ===========================================================================
# 3/13. .env File Secret Scanning (from Python audit)
# ===========================================================================
echo -e "${BOLD}[3/13] Scanning .env files for exposed secrets...${NC}"

while IFS= read -r file; do
    basename_f=$(basename "$file")
    [[ "$basename_f" == .env* ]] || continue
    [[ "$basename_f" =~ \.example$ ]] && continue
    [ ! -f "$file" ] && continue

    # Look for KEY=actual_secret (not KEY= or KEY=placeholder)
    matches=$(grep -nEi '^(API_?KEY|SECRET|PASSWORD|AUTH_?TOKEN|PRIVATE_?KEY|BOT_?TOKEN)\s*=\s*\S+' "$file" 2>/dev/null \
        | grep -viE '(placeholder|changeme|your|example|xxx)' \
        | head -5 || true)
    if [ -n "$matches" ]; then
        finding "CRITICAL" ".env Secret" "$file" \
            "$(echo "$matches" | head -1)" \
            "Ensure .env is in .gitignore — this file should NEVER be committed"
    fi
done < <(get_files)

# ===========================================================================
# 4/13. Hardcoded User Paths
# ===========================================================================
echo -e "${BOLD}[4/13] Scanning for hardcoded user paths...${NC}"

while IFS= read -r file; do
    is_binary "$file" && continue
    [ ! -f "$file" ] && continue

    # Skip files that document security findings
    [[ "$file" =~ \.security_baseline$ ]] && continue
    [[ "$file" =~ \.security_terms$ ]] && continue

    matches=$(grep -nE '/Users/[a-z][a-z0-9_.-]+/' "$file" 2>/dev/null \
        | grep -vE '(/Users/yourname/|/Users/user/|/Users/test/|\$HOME|Path\.home|os\.path\.expanduser|SCRIPT_DIR|example|placeholder)' \
        | head -5 || true)

    if [ -n "$matches" ]; then
        finding "HIGH" "Hardcoded User Path" "$file" \
            "$(echo "$matches" | head -1)" \
            "Use Path.home(), \$HOME, or SCRIPT_DIR instead of absolute user paths"
    fi
done < <(get_files)

# ===========================================================================
# 5/13. PII Patterns (SSN, email, phone, credit card)
# ===========================================================================
echo -e "${BOLD}[5/13] Scanning for PII patterns...${NC}"

while IFS= read -r file; do
    is_binary "$file" && continue
    [ ! -f "$file" ] && continue
    [[ "$file" =~ ^tests/ ]] && continue
    [[ "$file" =~ security_scan\.sh$ ]] && continue
    [[ "$file" =~ audit_security\.py$ ]] && continue
    [[ "$file" =~ pii_terms\.example ]] && continue
    [[ "$file" =~ SECURITY\.md$ ]] && continue
    [[ "$file" =~ \.security_terms\.example$ ]] && continue
    [[ "$file" =~ \.security_terms$ ]] && continue
    [[ "$file" =~ \.security_baseline$ ]] && continue

    # SSN pattern
    matches=$(grep -nE '\b[0-9]{3}-[0-9]{2}-[0-9]{4}\b' "$file" 2>/dev/null \
        | grep -vE '(example|123-45-6789|000-00-0000|XXX-XX-XXXX|regex|pattern|detect|format|test|nosec)' \
        | head -3 || true)
    if [ -n "$matches" ]; then
        finding "CRITICAL" "Possible SSN" "$file" \
            "$(echo "$matches" | head -1)" \
            "Remove or replace with placeholder (XXX-XX-XXXX)"
    fi

    # Email addresses
    matches=$(grep -nEio '\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b' "$file" 2>/dev/null \
        | grep -viE '(example\.com|example\.org|test\.com|noreply@|placeholder|user@|john\.doe|jane\.doe|foo@bar)' \
        | head -3 || true)
    if [ -n "$matches" ]; then
        finding "HIGH" "Real Email Address" "$file" \
            "$(echo "$matches" | head -1)" \
            "Replace with user@example.com or similar placeholder"
    fi

    # Phone numbers
    matches=$(grep -nE '\b(\+1[-.]?)?\(?[0-9]{3}\)?[-. ][0-9]{3}[-. ][0-9]{4}\b' "$file" 2>/dev/null \
        | grep -vE '(example|555-|000-|123-456|format|regex|pattern|detect|test|nosec)' \
        | head -3 || true)
    if [ -n "$matches" ]; then
        finding "MEDIUM" "Possible Phone Number" "$file" \
            "$(echo "$matches" | head -1)" \
            "Replace with (555) 555-0100 or similar placeholder"
    fi

    # Credit cards
    matches=$(grep -nE '\b[0-9]{4}[- ]?[0-9]{4}[- ]?[0-9]{4}[- ]?[0-9]{4}\b' "$file" 2>/dev/null \
        | grep -vE '(example|0000|1234|test|pattern|regex|detect|format|xxxx|nosec)' \
        | head -3 || true)
    if [ -n "$matches" ]; then
        finding "CRITICAL" "Possible Credit Card" "$file" \
            "$(echo "$matches" | head -1)" \
            "Remove immediately"
    fi
done < <(get_files)

# ===========================================================================
# 6/13. Internal Project References (.security_terms)
# ===========================================================================
echo -e "${BOLD}[6/13] Scanning for internal/private references...${NC}"

PRIVATE_TERMS_FILE="$PROJECT_ROOT/.security_terms"

if [ -f "$PRIVATE_TERMS_FILE" ]; then
    while IFS= read -r term; do
        [[ -z "$term" || "$term" =~ ^# ]] && continue

        while IFS= read -r file; do
            is_binary "$file" && continue
            [ ! -f "$file" ] && continue
            [[ "$file" =~ security_scan\.sh$ ]] && continue
            [[ "$file" =~ audit_security\.py$ ]] && continue
            [[ "$file" =~ \.security_terms$ ]] && continue
            [[ "$file" =~ \.security_baseline$ ]] && continue

            matches=$(grep -niF "$term" "$file" 2>/dev/null | head -3 || true)
            if [ -n "$matches" ]; then
                finding "HIGH" "Private Reference" "$file" \
                    "Contains private term '${term}'" \
                    "Replace with generic language or move file to gitignored location"
            fi
        done < <(get_files)
    done < "$PRIVATE_TERMS_FILE"
else
    echo -e "  ${DIM}No .security_terms file found (optional).${NC}"
fi

# ===========================================================================
# 7/13. Sensitive Files That Should Be Gitignored
# ===========================================================================
echo -e "${BOLD}[7/13] Checking for sensitive files that should be gitignored...${NC}"

SENSITIVE_FILES=(
    ".env"
    ".env.local"
    ".env.production"
    "secrets.json"
    "credentials.json"
    "service-account.json"
)

while IFS= read -r file; do
    basename_f=$(basename "$file")
    for sensitive in "${SENSITIVE_FILES[@]}"; do
        if [ "$basename_f" = "$sensitive" ]; then
            finding "CRITICAL" "Sensitive File Tracked" "$file" \
                "This file should be gitignored, not committed" \
                "Run: git rm --cached '$file' && add to .gitignore"
        fi
    done
done < <(get_files)

# ===========================================================================
# 8/13. Database / Binary / Log Files
# ===========================================================================
echo -e "${BOLD}[8/13] Checking for database and binary files...${NC}"

while IFS= read -r file; do
    case "$file" in
        *.db|*.sqlite|*.sqlite3)
            finding "HIGH" "Database File Tracked" "$file" \
                "Database files contain runtime data and shouldn't be committed" \
                "Add to .gitignore and run: git rm --cached '$file'"
            ;;
        *.log)
            finding "MEDIUM" "Log File Tracked" "$file" \
                "Log files may contain PII or sensitive runtime data" \
                "Add to .gitignore and run: git rm --cached '$file'"
            ;;
    esac
done < <(get_files)

# ===========================================================================
# 9/13. Dangerous Code Patterns (with # nosec suppression)
# ===========================================================================
echo -e "${BOLD}[9/13] Scanning for dangerous code patterns...${NC}"

while IFS= read -r file; do
    [[ "$file" =~ \.(py)$ ]] || continue
    [ ! -f "$file" ] && continue
    [[ "$file" =~ (SECURITY|security_scan|audit_security) ]] && continue

    # shell=True with variable input
    matches=$(grep -nE 'subprocess\.(run|call|Popen).*shell\s*=\s*True' "$file" 2>/dev/null \
        | grep -v '# nosec' | head -3 || true)
    if [ -n "$matches" ]; then
        finding "HIGH" "Shell Injection Risk" "$file" \
            "$(echo "$matches" | head -1)" \
            "Use subprocess.run([...]) with list args instead of shell=True"
    fi

    # verify=False on HTTPS requests
    matches=$(grep -nE 'verify\s*=\s*False' "$file" 2>/dev/null \
        | grep -v '# nosec' | head -3 || true)
    if [ -n "$matches" ]; then
        finding "MEDIUM" "SSL Verification Disabled" "$file" \
            "$(echo "$matches" | head -1)" \
            "Remove verify=False to enable certificate verification"
    fi

    # Binding to 0.0.0.0
    matches=$(grep -nE '(host\s*=\s*["\x27]0\.0\.0\.0|0\.0\.0\.0.*bind)' "$file" 2>/dev/null \
        | grep -v '# nosec' | head -3 || true)
    if [ -n "$matches" ]; then
        finding "MEDIUM" "Network-Exposed Server" "$file" \
            "$(echo "$matches" | head -1)" \
            "Bind to 127.0.0.1 for local-only access"
    fi

    # eval() or exec()
    matches=$(grep -nE '\b(eval|exec)\s*\(' "$file" 2>/dev/null \
        | grep -vE '(#.*comment|# nosec)' \
        | head -3 || true)
    if [ -n "$matches" ]; then
        finding "HIGH" "Dynamic Code Execution" "$file" \
            "$(echo "$matches" | head -1)" \
            "Avoid eval()/exec() — use safer alternatives"
    fi
done < <(get_files)

# ===========================================================================
# 10/13. Private Asset Visibility Check
# ===========================================================================
echo -e "${BOLD}[10/13] Checking private asset visibility...${NC}"

# Check if .hq-private/ exists but is NOT gitignored
if [ -d "$PROJECT_ROOT/.hq-private" ]; then
    if ! grep -qE '^\s*\.hq-private/?$' "$PROJECT_ROOT/.gitignore" 2>/dev/null; then
        finding "CRITICAL" "Private Assets Exposed" ".hq-private/" \
            ".hq-private/ directory exists but is NOT in .gitignore" \
            "Add '.hq-private/' to .gitignore immediately"
    fi
fi

# Check for files with HQ-VISIBILITY: private marker that are git-tracked
while IFS= read -r file; do
    is_binary "$file" && continue
    [ ! -f "$file" ] && continue

    matches=$(grep -nE '# HQ-VISIBILITY:\s*private' "$file" 2>/dev/null | head -3 || true)
    if [ -n "$matches" ]; then
        finding "HIGH" "Private HQ Asset Tracked" "$file" \
            "File contains HQ-VISIBILITY: private marker but is git-tracked" \
            "Move to .hq-private/ (gitignored) or remove the file from version control"
    fi
done < <(get_files)

# ===========================================================================
# 11/13. Commercial & Sensitivity Markers
# ===========================================================================
echo -e "${BOLD}[11/13] Checking for commercial/sensitivity markers...${NC}"

while IFS= read -r file; do
    is_binary "$file" && continue
    [ ! -f "$file" ] && continue
    [[ "$file" =~ security_scan\.sh$ ]] && continue
    [[ "$file" =~ audit_security\.py$ ]] && continue
    [[ "$file" =~ CLAUDE\.md$ ]] && continue
    [[ "$file" =~ SECURITY\.md$ ]] && continue
    [[ "$file" =~ CONVENTIONS\.md$ ]] && continue

    # COMMERCIAL marker
    matches=$(grep -nE '#\s*COMMERCIAL:' "$file" 2>/dev/null | head -3 || true)
    if [ -n "$matches" ]; then
        finding "HIGH" "Commercial IP Marker" "$file" \
            "$(echo "$matches" | head -1)" \
            "This file contains proprietary business logic. Keep in private repo or remove the marked code."
    fi

    # SECURITY-CONFIG marker
    matches=$(grep -nE '#\s*SECURITY-CONFIG:' "$file" 2>/dev/null | head -3 || true)
    if [ -n "$matches" ]; then
        finding "MEDIUM" "Security Config to Externalize" "$file" \
            "$(echo "$matches" | head -1)" \
            "Move hardcoded detection rules to a gitignored config file and load at runtime."
    fi

    # PRIVATE-DATA marker
    matches=$(grep -nE '#\s*PRIVATE-DATA:' "$file" 2>/dev/null | head -3 || true)
    if [ -n "$matches" ]; then
        finding "HIGH" "Private Data Reference" "$file" \
            "$(echo "$matches" | head -1)" \
            "Ensure private data is loaded from gitignored config, not committed to repo."
    fi
done < <(get_files)

# ===========================================================================
# 12/13. Compliance Checks (from Python audit)
# ===========================================================================
echo -e "${BOLD}[12/13] Running compliance checks...${NC}"

# --- .gitignore coverage ---
GITIGNORE="$PROJECT_ROOT/.gitignore"
if [ -f "$GITIGNORE" ]; then
    REQUIRED_GITIGNORE_ENTRIES=(
        ".env|Environment file with secrets"
        "*.db|Database files with runtime data"
        "config.yaml|User-specific configuration"
    )

    for entry_pair in "${REQUIRED_GITIGNORE_ENTRIES[@]}"; do
        entry="${entry_pair%%|*}"
        reason="${entry_pair#*|}"
        if ! grep -qF "$entry" "$GITIGNORE" 2>/dev/null; then
            finding "HIGH" "Gitignore Gap" ".gitignore" \
                "'${entry}' not in .gitignore (${reason})" \
                "Add '${entry}' to .gitignore"
        fi
    done
else
    finding "HIGH" "Missing Gitignore" "." \
        "No .gitignore found — sensitive files may be committed" \
        "Create a .gitignore from the _HQ template"
fi

# --- .env.example parity ---
if [ -f "$PROJECT_ROOT/.env" ] && [ ! -f "$PROJECT_ROOT/.env.example" ]; then
    finding "MEDIUM" "Missing .env.example" "." \
        ".env exists but .env.example is missing (needed for onboarding)" \
        "Create .env.example with placeholder values for all .env keys"
fi

# ===========================================================================
# 13/14. GitHub ToS / Content Policy Compliance
# ===========================================================================
# Scans for content that could violate GitHub's Terms of Service and
# Acceptable Use Policies. Covers all enforcement categories:
#   - Sexually obscene content (primary enforcement area — account bans)
#   - Violence, threats, and harassment
#   - Malware distribution intent
#   - CSAM references
#   - Privacy violations (doxxing)
#   - License bypass / cracking tools
#   - AI safety bypass language (abliterated/uncensored model promotion)
#   - Project-specific prohibited terms (.tos_terms)
#
# Reference: https://docs.github.com/en/site-policy/acceptable-use-policies
# ===========================================================================
echo -e "${BOLD}[13/14] Scanning for GitHub ToS / content policy compliance...${NC}"

while IFS= read -r file; do
    is_binary "$file" && continue
    [ ! -f "$file" ] && continue
    # Skip scanner itself and baseline/terms files
    [[ "$file" =~ security_scan\.sh$ ]] && continue
    [[ "$file" =~ \.security_baseline$ ]] && continue
    [[ "$file" =~ \.security_terms$ ]] && continue
    [[ "$file" =~ \.tos_terms$ ]] && continue

    # --- Sexually obscene content (GitHub's #1 enforcement area) ---
    # Catches explicit sexual language that serves no technical purpose
    matches=$(grep -niE '(pornograph|hentai|nsfw.*(content|image|generat)|sexually\s+explicit|erotic\s+(content|fiction|roleplay)|sex\s+scene|intimate\s+encounter|adult\s+content\s+generat)' "$file" 2>/dev/null \
        | grep -vE '(# nosec|detect|filter|block|scan|policy|flag|violat|prohibit|obscene)' \
        | head -3 || true)
    if [ -n "$matches" ]; then
        finding "CRITICAL" "Sexually Obscene Content" "$file" \
            "$(echo "$matches" | head -1)" \
            "Remove sexual content or move to gitignored file. GitHub bans accounts for this."
    fi

    # --- Violence and threats ---
    matches=$(grep -niE '(kill\s+(all|every|them)|death\s+threat|bomb\s+threat|shoot(ing)?\s+(up|them|people)|mass\s+(murder|shooting|violence)|genocide|ethnic\s+cleansing)' "$file" 2>/dev/null \
        | grep -vE '(# nosec|detect|filter|block|scan|test|pattern|threat.*detect|ThreatLevel)' \
        | head -3 || true)
    if [ -n "$matches" ]; then
        finding "CRITICAL" "Violent/Threatening Content" "$file" \
            "$(echo "$matches" | head -1)" \
            "Remove violent or threatening content. Violates GitHub Acceptable Use Policy."
    fi

    # --- Harassment and hate speech ---
    matches=$(grep -niE '(racial\s+slur|hate\s+speech|white\s+supremac|neo.?nazi|ethnic\s+slur)' "$file" 2>/dev/null \
        | grep -vE '(# nosec|detect|filter|block|scan|test|policy|flag|content.?modera)' \
        | head -3 || true)
    if [ -n "$matches" ]; then
        finding "HIGH" "Harassment/Hate Content" "$file" \
            "$(echo "$matches" | head -1)" \
            "Remove discriminatory content. Violates GitHub community guidelines."
    fi

    # --- CSAM references ---
    matches=$(grep -niE '(child\s+(porn|exploit|abuse\s+material)|csam|minor.*(sexual|exploit|nude|intimate)|underage.*(sexual|porn|nude|exploit))' "$file" 2>/dev/null \
        | grep -vE '(# nosec|detect|report|block|scan|policy|flag|prohibit|illegal)' \
        | head -3 || true)
    if [ -n "$matches" ]; then
        finding "CRITICAL" "CSAM Reference" "$file" \
            "$(echo "$matches" | head -1)" \
            "Remove immediately. CSAM content results in permanent ban and legal referral."
    fi

    # --- Active malware distribution ---
    # Not dual-use research — catches language indicating active distribution intent
    matches=$(grep -niE '(ransomware\s+(builder|kit|generat|deploy)|keylogger\s+(deploy|install|inject)|trojan\s+(builder|generat|deploy)|botnet\s+(command|deploy|build)|payload\s+delivery\s+system)' "$file" 2>/dev/null \
        | grep -vE '(# nosec|detect|scan|defense|protect|block|test|research|analysis|security)' \
        | head -3 || true)
    if [ -n "$matches" ]; then
        finding "CRITICAL" "Malware Distribution" "$file" \
            "$(echo "$matches" | head -1)" \
            "Remove malware distribution tools. GitHub prohibits active malware campaigns."
    fi

    # --- License bypass tools ---
    matches=$(grep -niE '(keygen|serial\s+(number\s+)?generat|crack(ed|ing|er)\s+(software|licen|serial)|license\s+bypass|activation\s+crack|warez|pirat(ed|ing)\s+software)' "$file" 2>/dev/null \
        | grep -vE '(# nosec|test|example|detect|security|cryptograph)' \
        | head -3 || true)
    if [ -n "$matches" ]; then
        finding "HIGH" "License Bypass Tool" "$file" \
            "$(echo "$matches" | head -1)" \
            "Remove license circumvention content. Violates GitHub IP/authenticity policy."
    fi

    # --- Privacy violations (doxxing) ---
    matches=$(grep -niE '(dox(x)?(ing|ed)?|leaked?\s+(address|phone|personal)|expose\s+(their|someone).*(address|identity|personal)|swat(t)?ing)' "$file" 2>/dev/null \
        | grep -vE '(# nosec|detect|prevent|security|protect|block|test|policy)' \
        | head -3 || true)
    if [ -n "$matches" ]; then
        finding "HIGH" "Privacy Violation / Doxxing" "$file" \
            "$(echo "$matches" | head -1)" \
            "Remove content related to exposing personal information."
    fi

    # --- AI safety bypass language ---
    # While tolerated in research repos, this language in non-research context is risky
    # and can trigger automated scanning. Flag for review.
    matches=$(grep -niE '(no\s+content\s+policy|no\s+safety\s+filter|no\s+refusal\s+instinct|never\s+refuse\s+a\s+request|uncensored\s+and\s+unrestricted|abliterat(e|ed|ion|ing)|bypass\s+(all\s+)?safety|remove\s+(all\s+)?guardrail|zero\s+refusal)' "$file" 2>/dev/null \
        | grep -vE '(# nosec|detect|scan|block|flag|security|test_.*\.py)' \
        | head -3 || true)
    if [ -n "$matches" ]; then
        finding "MEDIUM" "AI Safety Bypass Language" "$file" \
            "$(echo "$matches" | head -1)" \
            "Review: AI safety bypass language may trigger automated scanning. Move to gitignored config if needed for functionality."
    fi

    # --- Deceptive content / impersonation ---
    matches=$(grep -niE '(phishing\s+(template|kit|page|email)|impersonat(e|ing)\s+(github|microsoft|google|apple|amazon)|fake\s+(login|credential|auth)\s+(page|form|portal))' "$file" 2>/dev/null \
        | grep -vE '(# nosec|detect|scan|block|security|test|prevent|defense)' \
        | head -3 || true)
    if [ -n "$matches" ]; then
        finding "HIGH" "Deceptive Content" "$file" \
            "$(echo "$matches" | head -1)" \
            "Remove phishing/impersonation content. Violates GitHub fraud policy."
    fi

    # --- DRM circumvention ---
    matches=$(grep -niE '(drm[_\s]*(key|bypass|circumvent|crack|remov)|decrypt.*drm|strip.*drm|remove.*copy.?protect|circumvent.*protection.?measure|dmca.*1201|m3u8.*decrypt|mpd.*decrypt)' "$file" 2>/dev/null \
        | grep -vE '(# nosec|detect|scan|block|policy|test|legal|compliance|prohibit)' \
        | head -3 || true)
    if [ -n "$matches" ]; then
        finding "HIGH" "DRM Circumvention" "$file" \
            "$(echo "$matches" | head -1)" \
            "Remove DRM bypass content. May violate DMCA 1201 and GitHub ToS."
    fi

    # --- Course piracy / platform automation ---
    matches=$(grep -niE '(udemy.*(download|rip|extract|scrape)|coursera.*(automat|skip.*video|complete.*lab|take.*quiz|extract.*content)|skip.*video.*automat|automat.*(quiz|lab|course.?complet)|course.*(rip|pirat|download.*video))' "$file" 2>/dev/null \
        | grep -vE '(# nosec|detect|block|policy|test|prohibit)' \
        | head -3 || true)
    if [ -n "$matches" ]; then
        finding "HIGH" "Course Piracy / Platform Automation" "$file" \
            "$(echo "$matches" | head -1)" \
            "Remove references to automating or extracting content from paid platforms. Facilitates unauthorized access."
    fi

    # --- Credential harvesting ---
    matches=$(grep -niE '(credential[_\s]*(harvest|steal|dump|extract|capture)|password[_\s]*(harvest|steal|dump|capture)|cookie[_\s]*(extract|steal|hijack)|session[_\s]*(hijack|steal)|UserCred.?Hack)' "$file" 2>/dev/null \
        | grep -vE '(# nosec|detect|scan|block|security|test|prevent|defense|policy|audit)' \
        | head -3 || true)
    if [ -n "$matches" ]; then
        finding "CRITICAL" "Credential Harvesting" "$file" \
            "$(echo "$matches" | head -1)" \
            "Remove credential harvesting content. Violates GitHub acceptable use policy."
    fi

    # --- Anti-bot bypass tools (distribution intent) ---
    matches=$(grep -niE '(bypass.*(cloudflare|captcha|datadome|perimeterx|akamai|imperva|incapsula|aws.?waf)|captcha.*(solv|bypass|break|defeat)|anti.?bot.*(bypass|evad|defeat)|evasion.?engine|fingerprint.?spoof)' "$file" 2>/dev/null \
        | grep -vE '(# nosec|detect|scan|block|security|test|defense|protect|research.*only|waf.*config)' \
        | head -3 || true)
    if [ -n "$matches" ]; then
        finding "MEDIUM" "Anti-Bot Bypass Tool" "$file" \
            "$(echo "$matches" | head -1)" \
            "Review: Anti-bot bypass content may violate ToS if publicly distributed. Move to private/gitignored docs."
    fi

    # --- robots.txt violation promotion ---
    matches=$(grep -niE '(ignore.*robots\.txt|disregard.*robots\.txt|bypass.*robots\.txt|robots\.txt.*(ignor|bypass|disregard)|rude.?mode|rude.?stealth)' "$file" 2>/dev/null \
        | grep -vE '(# nosec|test|config.*default.*false|= False)' \
        | head -3 || true)
    if [ -n "$matches" ]; then
        finding "MEDIUM" "robots.txt Violation" "$file" \
            "$(echo "$matches" | head -1)" \
            "Review: Promoting robots.txt ignoring may violate GitHub ToS. Remove from public docs/README."
    fi

done < <(get_files)

# --- Project-specific ToS terms (.tos_terms) ---
# These are terms specific to YOUR project that should never appear in committed files.
# Designed for persona names, feature codenames, or other content you want to keep private.
TOS_TERMS_FILE="$PROJECT_ROOT/.tos_terms"

if [ -f "$TOS_TERMS_FILE" ]; then
    echo -e "  ${DIM}Loading project-specific ToS terms from .tos_terms...${NC}"
    while IFS= read -r term; do
        [[ -z "$term" || "$term" =~ ^# ]] && continue

        # Extract severity if provided (format: "SEVERITY|term" or just "term")
        if [[ "$term" == *"|"* ]]; then
            tos_severity="${term%%|*}"
            tos_term="${term#*|}"
        else
            tos_severity="HIGH"
            tos_term="$term"
        fi

        while IFS= read -r file; do
            is_binary "$file" && continue
            [ ! -f "$file" ] && continue
            [[ "$file" =~ security_scan\.sh$ ]] && continue
            [[ "$file" =~ \.tos_terms$ ]] && continue
            [[ "$file" =~ \.security_baseline$ ]] && continue
            [[ "$file" =~ \.gitignore$ ]] && continue

            matches=$(grep -niF "$tos_term" "$file" 2>/dev/null | head -3 || true)
            if [ -n "$matches" ]; then
                finding "$tos_severity" "ToS Prohibited Term" "$file" \
                    "Contains prohibited term '${tos_term}'" \
                    "Remove or move to gitignored file. This term should never be in committed code."
            fi
        done < <(get_files)
    done < "$TOS_TERMS_FILE"
else
    echo -e "  ${DIM}No .tos_terms file found (optional — add project-specific prohibited terms).${NC}"
fi

# ---------------------------------------------------------------------------
# 14/14. Ecosystem Reference Check (informational for private repos)
# ---------------------------------------------------------------------------
# Detects ecosystem-internal references that should not appear in public repos.
# Findings are warnings, not hard failures — review before publish.
echo -e "${BOLD}[14/14] Scanning for ecosystem references...${NC}"

ECOSYSTEM_PATTERNS=(
    "_HQ/"
    "hq-coord"
    "hq_mcp_server"
    "Tech_Projects"
    "from corerag"
    "from kendra"
    "from whowho"
    "import hq_coord"
    "localhost:8000"
    "localhost:8001"
    "localhost:8002"
    "localhost:8003"
    "localhost:8004"
    "localhost:8005"
    "localhost:8006"
)

for pattern in "${ECOSYSTEM_PATTERNS[@]}"; do
    while IFS= read -r file; do
        [[ -z "$file" ]] && continue
        # Skip agent config files, gitignore, and documentation references
        [[ "$file" =~ CLAUDE\.md$ ]] && continue
        [[ "$file" =~ ANTIGRAVITY\.md$ ]] && continue
        [[ "$file" =~ CODEX\.md$ ]] && continue
        [[ "$file" =~ GEMINI\.md$ ]] && continue
        [[ "$file" =~ AGENTS\.md$ ]] && continue
        [[ "$file" =~ \.gitignore$ ]] && continue
        [[ "$file" =~ \.security_baseline$ ]] && continue
        [[ "$file" =~ \.tos_terms$ ]] && continue
        [[ "$file" =~ conftest\.py$ ]] && continue

        while IFS=: read -r lineno content; do
            [[ "$content" =~ \#.*nosec ]] && continue
            finding "LOW" "Ecosystem Reference" "$file" \
                "Contains ecosystem reference '$pattern' at line $lineno. Review before public publish."
        done < <(grep -n "$pattern" "$file" 2>/dev/null || true)
    done < <(get_files)
done

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo -e "${BOLD}========================================${NC}"
if [ "$FINDINGS" -eq 0 ]; then
    if [ "$ACKNOWLEDGED" -gt 0 ]; then
        echo -e "${GREEN}${BOLD} CLEAN — ${ACKNOWLEDGED} acknowledged finding(s) only${NC}"
    else
        echo -e "${GREEN}${BOLD} CLEAN — No security findings detected${NC}"
    fi
    echo -e "${BOLD}========================================${NC}"
    echo ""
    exit 0
else
    echo -e "${RED}${BOLD} FOUND ${FINDINGS} ISSUE(S)${NC}"
    if [ "$ACKNOWLEDGED" -gt 0 ]; then
        echo -e "${DIM} (plus ${ACKNOWLEDGED} acknowledged baseline finding(s))${NC}"
    fi
    echo -e "${BOLD}========================================${NC}"
    echo ""
    echo -e "Run with ${CYAN}--fix${NC} flag to see suggested remediation."
    echo -e "Add findings to ${CYAN}.security_baseline${NC} to acknowledge known issues."
    echo -e "Use ${CYAN}# nosec${NC} inline to suppress individual code pattern matches."
    echo ""
    exit 1
fi
