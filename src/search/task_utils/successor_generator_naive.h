#ifndef TASK_UTILS_SUCCESSOR_GENERATOR_NAIVE_H
#define TASK_UTILS_SUCCESSOR_GENERATOR_NAIVE_H

#include "successor_generator_internals.h" // ist das eigentlich in ORdunung? ich wollte eigene Klasse machen, damit es übersichtlciher ist.
#include "../abstract_task.h"

#include <vector>

class TaskProxy;

namespace successor_generator {
class GeneratorNaive : public GeneratorBase {
    struct Entry {
        std::vector<FactPair> preconditions;  // Datenstruktur von Naive
        OperatorID op;
    };
    std::vector<Entry> operators;

public:
    explicit GeneratorNaive(const TaskProxy &task_proxy);

    virtual void generate_applicable_ops(
        const std::vector<int> &state,
        std::vector<OperatorID> &applicable_ops) const override;
};
}

#endif
