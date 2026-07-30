#include "successor_generator.h"

#include "successor_generator_factory.h"
#include "successor_generator_internals.h"
#include "successor_generator_naive.h"
#include "successor_generator_watched_literals.h"

#include "../abstract_task.h"
#include "../utils/logging.h"
#include "../utils/system.h"

#include <algorithm>
#include <cstdlib>

using namespace std;

namespace successor_generator {
static unique_ptr<GeneratorBase> create_root(
    const TaskProxy &task_proxy, bool use_naive, bool use_watched_literals) {
    if (use_watched_literals)
        return make_unique<GeneratorWatchedLiterals>(task_proxy);
    if (use_naive)
        return make_unique<GeneratorNaive>(task_proxy);
    return SuccessorGeneratorFactory(task_proxy).create(); // Match tree
}

SuccessorGenerator::SuccessorGenerator(const TaskProxy &task_proxy)
    : use_naive(getenv("DOWNWARD_SG_NAIVE") != nullptr),
      use_watched_literals(getenv("DOWNWARD_SG_WATCHED_LITERALS") != nullptr),
      compare_with_match_tree(getenv("DOWNWARD_SG_COMPARE") != nullptr),
      root(create_root(task_proxy, use_naive, use_watched_literals)),
      timer(false),
      num_calls(0),
      num_compared(0) {
    if (compare_with_match_tree) {
        reference = SuccessorGeneratorFactory(task_proxy).create();
    }
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
    int size_before = applicable_ops.size();
    timer.resume();
    root->generate_applicable_ops(unpacked, applicable_ops);
    timer.stop();
    ++num_calls;
    if (compare_with_match_tree) {
        check_against_reference(unpacked, applicable_ops, size_before);
    }
}

void SuccessorGenerator::check_against_reference(
    const vector<int> &state, const vector<OperatorID> &applicable_ops,
    int size_before) const {
    vector<OperatorID> from_root(
        applicable_ops.begin() + size_before, applicable_ops.end());
    vector<OperatorID> from_reference;
    reference->generate_applicable_ops(state, from_reference);

    sort(from_root.begin(), from_root.end());
    sort(from_reference.begin(), from_reference.end());
    ++num_compared;

    if (from_root == from_reference) {
        return;
    }

    utils::g_log << "Successor generator MISMATCH at comparison "
                 << num_compared << endl;
    utils::g_log << "State:";
    for (int value : state) {
        utils::g_log << " " << value;
    }
    utils::g_log << endl;
    utils::g_log << "Tested generator returned " << from_root.size()
                 << " operators:";
    for (OperatorID op : from_root) {
        utils::g_log << " " << op.get_index();
    }
    utils::g_log << endl;
    utils::g_log << "Match tree returned " << from_reference.size()
                 << " operators:";
    for (OperatorID op : from_reference) {
        utils::g_log << " " << op.get_index();
    }
    utils::g_log << endl;
    ABORT("successor generator comparison failed");
}

void SuccessorGenerator::print_statistics() const {
    string method;
    if (use_watched_literals) {
        method = "watched literals";
    } else if (use_naive) {
        method = "naive";
    } else {
        method = "match tree";
    }
    utils::g_log << "Successor generator method: " << method << endl;
    utils::g_log << "Successor generator calls: " << num_calls << endl;
    if (compare_with_match_tree) {
        utils::g_log << "Successor generator comparisons against match tree: "
                     << num_compared << " (all identical)" << endl;
    }
    utils::g_log << "Time for successor generation: " << timer << endl;
}

PerTaskInformation<SuccessorGenerator> g_successor_generators;
}
