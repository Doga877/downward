#include "successor_generator.h"

#include "successor_generator_factory.h"
#include "successor_generator_internals.h"
#include "successor_generator_naive.h"

#include "../abstract_task.h"
#include "../utils/logging.h"

#include <cstdlib>

using namespace std;

namespace successor_generator {
static unique_ptr<GeneratorBase> create_root(
    const TaskProxy &task_proxy, bool use_naive) {
    if (use_naive)
        return make_unique<GeneratorNaive>(task_proxy);
    return SuccessorGeneratorFactory(task_proxy).create();
}

SuccessorGenerator::SuccessorGenerator(const TaskProxy &task_proxy)
    : use_naive(getenv("DOWNWARD_SG_NAIVE") != nullptr),
      root(create_root(task_proxy, use_naive)),
      timer(false),
      num_calls(0) {
}

SuccessorGenerator::~SuccessorGenerator() = default;

void SuccessorGenerator::generate_applicable_ops(
    const State &state, vector<OperatorID> &applicable_ops) const {
    // Unpacking the state is preparation that every successor-generation
    // method (match tree, naive, watched literals) needs alike; it is not
    // part of the generator's own work, so we do it *outside* the timed
    // region to measure only the tree traversal itself.
    state.unpack();
    const vector<int> &unpacked = state.get_unpacked_values();
    timer.resume();
    root->generate_applicable_ops(unpacked, applicable_ops);
    timer.stop();
    ++num_calls;
}

void SuccessorGenerator::print_statistics() const {
    utils::g_log << "Successor generator method: "<< (use_naive ? "naive" : "match tree") << endl;
    utils::g_log << "Successor generator calls: " << num_calls << endl;
    utils::g_log << "Time for successor generation: " << timer << endl;
}

PerTaskInformation<SuccessorGenerator> g_successor_generators;
}
