#ifndef TASK_UTILS_SUCCESSOR_GENERATOR_MARKING_H
#define TASK_UTILS_SUCCESSOR_GENERATOR_MARKING_H

#include "successor_generator_internals.h"
#include "../abstract_task.h"

#include <vector>

class TaskProxy;

namespace successor_generator {
class GeneratorMarking : public GeneratorBase {
    std::vector<int> num_preconditions;
    std::vector<std::vector<std::vector<int>>> precondition_to_operators;
    std::vector<OperatorID> operators_without_preconditions;

    mutable std::vector<int> count_precondition;
    mutable std::vector<int> last_seen;
    mutable int current_round;

public:
    explicit GeneratorMarking(const TaskProxy &task_proxy);

    virtual void generate_applicable_ops(
        const std::vector<int> &state,
        std::vector<OperatorID> &applicable_ops) const override;
};
}

#endif
