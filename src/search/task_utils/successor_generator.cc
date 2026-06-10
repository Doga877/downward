#include "successor_generator.h"

#include "successor_generator_factory.h"
#include "successor_generator_internals.h"

#include "../abstract_task.h"
#include "../utils/logging.h"

using namespace std;

namespace successor_generator {
SuccessorGenerator::SuccessorGenerator(const TaskProxy &task_proxy)
    : root(SuccessorGeneratorFactory(task_proxy).create()),
      timer(false),
      num_calls(0) {
}

SuccessorGenerator::~SuccessorGenerator() = default;

void SuccessorGenerator::generate_applicable_ops(
    const State &state, vector<OperatorID> &applicable_ops) const {
    timer.resume();
    state.unpack();
    root->generate_applicable_ops(state.get_unpacked_values(), applicable_ops);
    timer.stop();
    ++num_calls;
}

void SuccessorGenerator::print_statistics() const {
    utils::g_log << "Successor generator calls: " << num_calls << endl;
    utils::g_log << "Time for successor generation: " << timer << endl;
}

PerTaskInformation<SuccessorGenerator> g_successor_generators;
}
