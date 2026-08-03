#include "successor_generator.h"

#include "successor_generator_factory.h"
#include "successor_generator_internals.h"
#include "successor_generator_naive.h"
#include "successor_generator_watched_literals.h"
#include "successor_generator_marking.h"

#include "../abstract_task.h"
#include "../utils/logging.h"

#include <cstdlib>

using namespace std;

namespace successor_generator {
// ZEITMESSUNG (Bau): Die Bauzeit dieses create_root()-Aufrufs wird in search_algorithm.cc gemessen (Timer successor_generator_timer,
// Ausgabe "time for successor generation creation"). 
// Diese Messung enthält: den kompletten create_root()-Aufruf (je nach Variante den Konstruktor von GeneratorNaive / GeneratorWatchedLiterals / GeneratorMarking, oder  SuccessorGeneratorFactory::create() für den Match Tree)
// und PerTaskInformation-Lookup g_successor_generators[task_proxy], der diesen Konstruktor auslöst.
static unique_ptr<GeneratorBase> create_root(
    const TaskProxy &task_proxy, bool use_naive, bool use_watched_literals,
    bool use_marking) {
    if (use_watched_literals)
        return make_unique<GeneratorWatchedLiterals>(task_proxy);
    if (use_naive)
        return make_unique<GeneratorNaive>(task_proxy);
    if (use_marking)
        return make_unique<GeneratorMarking>(task_proxy);
    return SuccessorGeneratorFactory(task_proxy).create(); // Match tree
}

static string generator_name_for_log(
    bool use_naive, bool use_watched_literals, bool use_marking) {
    if (use_watched_literals)
        return "watched-literals";
    if (use_naive)
        return "naive";
    if (use_marking)
        return "marking";
    return "match-tree";
}

SuccessorGenerator::SuccessorGenerator(const TaskProxy &task_proxy)
    : use_naive(getenv("DOWNWARD_SG_NAIVE") != nullptr),
      use_watched_literals(getenv("DOWNWARD_SG_WATCHED_LITERALS") != nullptr),
      use_marking(getenv("DOWNWARD_SG_MARKING") != nullptr),
      log_applicable_ops(getenv("DOWNWARD_SG_LOG") != nullptr),
      log_method_name(generator_name_for_log(
          use_naive, use_watched_literals, use_marking)),
      root(create_root(
               task_proxy, use_naive, use_watched_literals, use_marking)),
      timer(false),
      num_calls(0) {
}

SuccessorGenerator::~SuccessorGenerator() = default;

void SuccessorGenerator::generate_applicable_ops(
    const State &state, vector<OperatorID> &applicable_ops) const {
    state.unpack();
    const vector<int> &unpacked = state.get_unpacked_values();
    int size_before = applicable_ops.size();
    timer.resume();
    root->generate_applicable_ops(unpacked, applicable_ops);
    timer.stop();
    ++num_calls;
    if (log_applicable_ops) {
        log_call(unpacked, applicable_ops, size_before);
    }
}

void SuccessorGenerator::log_call(
    const vector<int> &state, const vector<OperatorID> &applicable_ops,
    int size_before) const {
    utils::g_log << "SG_LOG call=" << num_calls
                 << " algorithm=" << log_method_name << " state=";
    int num_variables = state.size();
    for (int i = 0; i < num_variables; ++i) {
        if (i > 0)
            utils::g_log << ",";
        utils::g_log << state[i];
    }
    utils::g_log << " ops=";
    int num_ops = applicable_ops.size();
    for (int i = size_before; i < num_ops; ++i) {
        if (i > size_before)
            utils::g_log << ",";
        utils::g_log << applicable_ops[i].get_index();
    }
    utils::g_log << endl;
}

void SuccessorGenerator::print_statistics() const {
    string method;
    if (use_watched_literals) {
        method = "watched literals";
    } else if (use_naive) {
        method = "naive";
    } else if (use_marking) {
        method = "marking";
    } else {
        method = "match tree";
    }
    utils::g_log << "Successor generator method: " << method << endl;
    utils::g_log << "Successor generator calls: " << num_calls << endl;
    utils::g_log << "Time for successor generation: " << timer << endl;
}

PerTaskInformation<SuccessorGenerator> g_successor_generators;
}
