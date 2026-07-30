#ifndef TASK_UTILS_SUCCESSOR_GENERATOR_WATCHED_LITERALS_H
#define TASK_UTILS_SUCCESSOR_GENERATOR_WATCHED_LITERALS_H

#include "successor_generator_internals.h"
#include "../abstract_task.h"

#include <vector>

class TaskProxy;

namespace successor_generator {
class GeneratorWatchedLiterals : public GeneratorBase {
    struct Entry {
        std::vector<FactPair> preconditions; // (var,  value) paar wie bei naive
        OperatorID op;
        mutable int watched_position;
    };

    std::vector<Entry> operators;
    std::vector<OperatorID> operators_without_preconditions; //  Diese Operatoren sind in jedem Zustand anwendbar und können nichts beobachten.

    mutable std::vector<std::vector<std::vector<int>>> watchlist; // watchlist[var][wert]
    mutable std::vector<int> woken_entries;

    int find_unsatisfied_precondition(const Entry &entry, const std::vector<int> &state) const;

    void start_watching(int entry_id, int position) const;

public:
    explicit GeneratorWatchedLiterals(const TaskProxy &task_proxy);

    virtual void generate_applicable_ops(
        const std::vector<int> &state,
        std::vector<OperatorID> &applicable_ops) const override;
};
}

#endif
