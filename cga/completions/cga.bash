# bash completion for the cga dispatcher.
#
# Enable with:
#   source /path/to/repo/cga/completions/cga.bash
# (or symlink it into /etc/bash_completion.d/ or ~/.local/share/bash-completion/completions/).
#
# Behaviour:
#   cga <TAB>            list every command (short and long names)
#   cga run <TAB>        list analysis dashboard lifecycle operations
#   cga chain <TAB>      list workflow chain operations
#   cga db <TAB>         list plan, build, and validate
#   cga db validate <TAB> list database validation operations
#   cga llm context <TAB> list Bench and Unified View context sources

_cga() {
    local cur cga
    cur="${COMP_WORDS[COMP_CWORD]}"
    cga="${COMP_WORDS[0]}"

    if [[ "${COMP_WORDS[1]-}" =~ ^(show|open|related)$ ]]; then
        if declare -F _get_comp_words_by_ref >/dev/null; then
            _get_comp_words_by_ref -n : cur
        fi
        if [ "${COMP_WORDS[COMP_CWORD-1]}" = --session-file ]; then
            COMPREPLY=($(compgen -f -- "$cur"))
            return 0
        fi
        case "$cur" in
            -*) COMPREPLY=($(compgen -W "-h --help --registry --session-file --chain --at --json --url --print-url" -- "$cur")) ;;
            *) COMPREPLY=($(compgen -W "$(CGA_OUTPUT_JSON=0 "$cga" show --registry 2>/dev/null | awk '{print $1}')" -- "$cur")) ;;
        esac
        if declare -F _ltrim_colon_completions >/dev/null; then
            _ltrim_colon_completions "$cur"
        fi
        return 0
    fi

    if [ "$COMP_CWORD" -eq 1 ]; then
        # Exact short acronym expands to its explicit long name.
        local lng
        lng="$("$cga" __long "$cur" 2>/dev/null || true)"
        if [ -n "$lng" ] && [ "$lng" != "$cur" ]; then
            COMPREPLY=("$lng")
            return 0
        fi

        COMPREPLY=($(compgen -W "$("$cga" __tools 2>/dev/null)" -- "$cur"))
        return 0
    fi

    if [ "$COMP_CWORD" -ge 3 ] && [[ "${COMP_WORDS[1]-}" =~ ^(h|help)$ ]]; then
        local sample_index
        case "${COMP_WORDS[2]-}" in
            sample|s)
                if [ "$COMP_CWORD" -eq 3 ]; then
                    COMPREPLY=($(compgen -W "05" -- "$cur"))
                    return 0
                fi
                [ "${COMP_WORDS[3]-}" = 05 ] || return 0
                sample_index=4
                ;;
            sample-05) sample_index=3 ;;
            *)
                if [ "$COMP_CWORD" -eq 3 ]; then
                    COMPREPLY=($(compgen -W "$("$cga" __subs "${COMP_WORDS[2]}" 2>/dev/null) -h --help" -- "$cur"))
                else
                    COMPREPLY=($(compgen -W "-h --help" -- "$cur"))
                fi
                return 0
                ;;
        esac
        if [ "$sample_index" -gt 0 ]; then
            if [ "$COMP_CWORD" -eq "$sample_index" ]; then
                COMPREPLY=($(compgen -W "$("$cga" __sample_steps)" -- "$cur"))
            elif [ "$COMP_CWORD" -eq "$((sample_index + 1))" ]; then
                COMPREPLY=($(compgen -W "run r" -- "$cur"))
            fi
            return 0
        fi
    fi

    if [ "$COMP_CWORD" -eq 2 ]; then
        local tok="${COMP_WORDS[1]}" subs
        subs="$("$cga" __subs "$tok" 2>/dev/null)"
        case "$cur" in
            -*)
                case "$tok" in
                    dfg|data-flow-graph|cfg|control-flow-graph)
                        COMPREPLY=($(compgen -W "-h --help -m --markdown -d --dot -r --render --manifest --session" -- "$cur"))
                        ;;
                    view)
                        COMPREPLY=($(compgen -W "-h --help --dump --capture --export --label --timeout" -- "$cur"))
                        ;;
                    *) COMPREPLY=($(compgen -W "-h --help" -- "$cur")) ;;
                esac
                ;;
            *)  COMPREPLY=($(compgen -W "$subs" -- "$cur")) ;;
        esac
        return 0
    fi

    if [[ "${COMP_WORDS[1]-}" =~ ^(a|assist)$ ]] &&
            [[ "${COMP_WORDS[2]-}" =~ ^(d|database-build)$ ]]; then
        if [ "$COMP_CWORD" -eq 3 ]; then
            COMPREPLY=($(compgen -W "fetch build index export -h --help" -- "$cur"))
        else
            case "${COMP_WORDS[3]-}" in
                fetch) COMPREPLY=($(compgen -W "--git --ref --archive --owner --repo --language --use-llm --llm-attempts -h --help" -- "$cur")) ;;
                build) COMPREPLY=($(compgen -W "--mode --command --use-llm --llm-attempts -h --help" -- "$cur")) ;;
                index) COMPREPLY=($(compgen -W "--allow-partial -h --help" -- "$cur")) ;;
                export) COMPREPLY=($(compgen -W "--base-url -h --help" -- "$cur")) ;;
            esac
        fi
        return 0
    fi

    if [[ "${COMP_WORDS[1]-}" =~ ^(a|assist)$ ]] &&
            [[ "${COMP_WORDS[2]-}" =~ ^(q|query-writing)$ ]]; then
        if [ "$COMP_CWORD" -eq 3 ]; then
            COMPREPLY=($(compgen -W "start catalogue select-databases download prepare save publish -h --help" -- "$cur"))
        else
            case "${COMP_WORDS[3]-}" in
                select-databases) COMPREPLY=($(compgen -W "--rows --search -h --help" -- "$cur")) ;;
                prepare) COMPREPLY=($(compgen -W "--databases -h --help" -- "$cur")) ;;
                save) COMPREPLY=($(compgen -W "--source -h --help" -- "$cur")) ;;
                publish) COMPREPLY=($(compgen -W "--name -h --help" -- "$cur")) ;;
            esac
        fi
        return 0
    fi

    if [ "$COMP_CWORD" -eq 3 ] &&
            { [ "${COMP_WORDS[1]}" = "db" ] ||
              [ "${COMP_WORDS[1]}" = "database" ]; }; then
        local action="${COMP_WORDS[2]}" subs
        subs="$("$cga" __subs "db-${action}" 2>/dev/null)"
        case "$cur" in
            -*) COMPREPLY=($(compgen -W "-h --help" -- "$cur")) ;;
            *) COMPREPLY=($(compgen -W "$subs" -- "$cur")) ;;
        esac
        return 0
    fi

    if [ "${COMP_WORDS[1]}" = llm ]; then
        local action="${COMP_WORDS[2]}" scope flags
        case "$action" in
            context)
                if [ "$COMP_CWORD" -eq 3 ]; then
                    COMPREPLY=($(compgen -W "bench unified -h --help" -- "$cur"))
                    return 0
                fi
                scope="${COMP_WORDS[3]}"
                ;;
            cb) scope=bench ;;
            cu) scope=unified ;;
            *) return 0 ;;
        esac
        flags="-h --help --show-html-endpoint --show-json-endpoint --show-docs --json --port"
        case "$scope" in
            bench)
                if [ "${COMP_WORDS[COMP_CWORD-1]}" = --session-file ]; then
                    COMPREPLY=($(compgen -f -- "$cur"))
                    return 0
                fi
                flags+=" --session-file"
                ;;
            unified) flags+=" --detail --include-sensitive" ;;
            *) return 0 ;;
        esac
        COMPREPLY=($(compgen -W "$flags" -- "$cur"))
        return 0
    fi

    return 0
}

complete -F _cga cga
