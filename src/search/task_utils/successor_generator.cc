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

SuccessorGenerator::SuccessorGenerator(const TaskProxy &task_proxy)
    : use_naive(getenv("DOWNWARD_SG_NAIVE") != nullptr),
      use_watched_literals(getenv("DOWNWARD_SG_WATCHED_LITERALS") != nullptr),
      use_marking(getenv("DOWNWARD_SG_MARKING") != nullptr),
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
    timer.resume();
    root->generate_applicable_ops(unpacked, applicable_ops);
    timer.stop();
    ++num_calls;
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
