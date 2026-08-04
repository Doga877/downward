#ifndef TASK_UTILS_SUCCESSOR_GENERATOR_H
#define TASK_UTILS_SUCCESSOR_GENERATOR_H

#include "../per_task_information.h"
#include "../utils/timer.h"

#include <memory>
#include <string>
#include <vector>

class OperatorID;
class State;
class TaskProxy;

namespace successor_generator {
class GeneratorBase;

class SuccessorGenerator {
    bool use_naive;
    bool use_watched_literals;
    bool use_marking;
    bool compare_with_match_tree;
    bool log_applicable_ops;
    std::string log_method_name;
    std::unique_ptr<GeneratorBase> root;
    std::unique_ptr<GeneratorBase> reference;
    mutable utils::Timer timer;
    mutable long num_calls;
    mutable long num_compared;

    void check_against_reference(
        const std::vector<int> &state,
        const std::vector<OperatorID> &applicable_ops,
        int size_before) const;

    void log_call(
        const std::vector<int> &state,
        const std::vector<OperatorID> &applicable_ops,
        int size_before) const;

public:
    explicit SuccessorGenerator(const TaskProxy &task_proxy);
    /*
      We cannot use the default destructor (implicitly or explicitly)
      here because GeneratorBase is a forward declaration and the
      incomplete type cannot be destroyed.
    */
    ~SuccessorGenerator();

    void generate_applicable_ops(
        const State &state, std::vector<OperatorID> &applicable_ops) const;
    void print_statistics() const;
};

extern PerTaskInformation<SuccessorGenerator> g_successor_generators;
}

#endif
