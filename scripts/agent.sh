#!/bin/bash
# Agent helper script for GitHub issue management
# Usage: ./scripts/agent.sh [command] [args]

set -e

REPO="MTG-Thomas/skra"
COMMAND=${1:-help}

show_help() {
    cat << EOF
Agent helper script for managing GitHub issues

Commands:
    list [agent-name]       List issues claimed by agent (OpenCode or Kilo)
    claim <issue> [agent]   Claim an issue (defaults to OpenCode)
    unclaim <issue>         Remove agent labels from issue
    progress <issue>        Post a progress comment
    done <issue>            Mark issue as ready for review
    blocked <issue>         Mark issue as blocked
    next                    Show next available high-priority issue

Examples:
    ./scripts/agent.sh list OpenCode
    ./scripts/agent.sh claim 12
    ./scripts/agent.sh claim 12 Kilo
    ./scripts/agent.sh progress 12
    ./scripts/agent.sh done 12

See docs/AGENTS.md for full workflow documentation.
EOF
}

list_issues() {
    local agent=${2:-OpenCode}
    echo "=== Issues claimed by $agent ==="
    gh issue list --repo "$REPO" --label "$agent" --state open
}

claim_issue() {
    local issue=$2
    local agent=${3:-OpenCode}
    
    if [ -z "$issue" ]; then
        echo "Error: Issue number required"
        echo "Usage: ./scripts/agent.sh claim <issue-number> [agent-name]"
        exit 1
    fi
    
    echo "Claiming issue #$issue for $agent..."
    gh api "repos/$REPO/issues/$issue/labels" -X POST \
        -f "labels[]=$agent" \
        -f "labels[]=in-progress" 2>/dev/null || true
    
    # Remove conflicting agent label if exists
    if [ "$agent" = "OpenCode" ]; then
        gh api "repos/$REPO/issues/$issue/labels/Kilo" -X DELETE 2>/dev/null || true
    else
        gh api "repos/$REPO/issues/$issue/labels/OpenCode" -X DELETE 2>/dev/null || true
    fi
    
    echo "Issue #$issue claimed by $agent"
}

unclaim_issue() {
    local issue=$2
    
    if [ -z "$issue" ]; then
        echo "Error: Issue number required"
        exit 1
    fi
    
    echo "Unclaiming issue #$issue..."
    gh api "repos/$REPO/issues/$issue/labels/OpenCode" -X DELETE 2>/dev/null || true
    gh api "repos/$REPO/issues/$issue/labels/Kilo" -X DELETE 2>/dev/null || true
    gh api "repos/$REPO/issues/$issue/labels/in-progress" -X DELETE 2>/dev/null || true
    
    echo "Issue #$issue unclaimed"
}

post_progress() {
    local issue=$2
    
    if [ -z "$issue" ]; then
        echo "Error: Issue number required"
        exit 1
    fi
    
    # Check if agent is OpenCode or Kilo
    local labels=$(gh api "repos/$REPO/issues/$issue" --jq '.labels[].name' 2>/dev/null || echo "")
    local agent="Agent"
    if echo "$labels" | grep -q "OpenCode"; then
        agent="OpenCode"
    elif echo "$labels" | grep -q "Kilo"; then
        agent="Kilo"
    fi
    
    echo "Posting progress comment to issue #$issue..."
    gh api "repos/$REPO/issues/$issue/comments" -X POST \
        -f "body=**Update from $agent:**\n\n[Describe your progress here]\n\n- [x] Task 1\n- [ ] Task 2\n- [ ] Task 3"
    
    echo "Comment posted"
}

mark_done() {
    local issue=$2
    
    if [ -z "$issue" ]; then
        echo "Error: Issue number required"
        exit 1
    fi
    
    echo "Marking issue #$issue as ready for review..."
    gh api "repos/$REPO/issues/$issue/labels/in-progress" -X DELETE 2>/dev/null || true
    gh api "repos/$REPO/issues/$issue/labels" -X POST \
        -f "labels[]=ready-to-merge" 2>/dev/null || true
    
    # Post completion comment
    gh api "repos/$REPO/issues/$issue/comments" -X POST \
        -f "body=**Done:** All acceptance criteria met.\n\nReady for review and merge."
    
    echo "Issue #$issue marked as ready-to-merge"
}

mark_blocked() {
    local issue=$2
    
    if [ -z "$issue" ]; then
        echo "Error: Issue number required"
        exit 1
    fi
    
    echo "Marking issue #$issue as blocked..."
    gh api "repos/$REPO/issues/$issue/labels" -X POST \
        -f "labels[]=blocked" 2>/dev/null || true
    
    gh api "repos/$REPO/issues/$issue/comments" -X POST \
        -f "body=**Blocked:**\n\n[Describe what's blocking you and what you need]\n\ncc: @MTG-Thomas"
    
    echo "Issue #$issue marked as blocked"
}

show_next() {
    echo "=== Next available high-priority issues ==="
    gh issue list --repo "$REPO" --label "P1-high" --state open | head -10
    
    echo ""
    echo "=== Medium priority issues ==="
    gh issue list --repo "$REPO" --label "P2-medium" --state open | head -5
}

case $COMMAND in
    list)
        list_issues "$@"
        ;;
    claim)
        claim_issue "$@"
        ;;
    unclaim)
        unclaim_issue "$@"
        ;;
    progress)
        post_progress "$@"
        ;;
    done)
        mark_done "$@"
        ;;
    blocked)
        mark_blocked "$@"
        ;;
    next)
        show_next
        ;;
    help|*)
        show_help
        ;;
esac
