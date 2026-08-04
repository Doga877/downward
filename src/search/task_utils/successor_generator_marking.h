#ifndef TASK_UTILS_SUCCESSOR_GENERATOR_MARKING_H
#define TASK_UTILS_SUCCESSOR_GENERATOR_MARKING_H

#include "successor_generator_internals.h"
#include "../abstract_task.h"

#include <vector>

class TaskProxy;

namespace successor_generator {
class GeneratorMarking : public GeneratorBase {
    struct Entry {
        int num_preconditions;
        int count_precondition;
        int last_seen;
    };

    std::vector<std::vector<std::vector<int>>> precondition_to_operators;
    std::vector<OperatorID> operators_without_preconditions;

    mutable std::vector<Entry> operators;
    mutable int current_round;

public:
    explicit GeneratorMarking(const TaskProxy &task_proxy);

    virtual void generate_applicable_ops(
        const std::vector<int> &state,
        std::vector<OperatorID> &applicable_ops) const override;
};
}

#endif
