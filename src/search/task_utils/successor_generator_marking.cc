#include "successor_generator_marking.h"

#include "../task_proxy.h"

using namespace std;

namespace successor_generator {
GeneratorMarking::GeneratorMarking(const TaskProxy &task_proxy) {
    VariablesProxy all_variables = task_proxy.get_variables();
    precondition_to_operators.resize(all_variables.size());  // precondition_to_operators = [ [] , [] , ... ] für jede Zustandsvariable ein Unter-Array (inverser Index: Fakt -> Operatoren, die ihn brauchen), preconditons
    for (VariableProxy variable : all_variables) { // für jeden Wert (value) der Variable ein Unter-Array kriert: precondition_to_operators[0] = [ {} , {} , {} ] -- so viele Unter-Arrays wie die Domäne der Variable Werte hat
        int variable_id = variable.get_id();  // die precondition variable index
        int num_values = variable.get_domain_size(); // anzahl optionen pro  precondition
        precondition_to_operators[variable_id].resize(num_values);  // precondition_to_operators = [ [{},{},{}] , [...] , [] , ... ]
    }

    OperatorsProxy all_operators = task_proxy.get_operators();
    int num_operators = all_operators.size(); // anzahl der operatoren 
    num_preconditions.resize(num_operators, 0); // num_preconditions  = [0,0,0, ...]
    count_precondition.resize(num_operators, 0); // zählt die preconditions runter zur laufzeit
    last_seen.resize(num_operators, 0);  // pro Operator, in welcher Runde er zuletzt angefasst wurde
    current_round = 0; // aktuelle Rundennummer,  ersten Aufruf von generate_applicable_ops wird er auf 1 erhöht

    for (OperatorProxy op : all_operators) {
        int op_id = op.get_id();
        num_preconditions[op_id] = op.get_preconditions().size(); // anzah der precondtions pro op. eingetragen

        if (num_preconditions[op_id] == 0) {
            operators_without_preconditions.push_back(OperatorID(op_id));  // op ohne precontion kommt auf eine seperate liste
        }

        for (FactProxy precondition : op.get_preconditions()) { // jede einzelne precondition 
            FactPair fact = precondition.get_pair(); 
            int variable_id = fact.var; // welche Zustandsvariable bespiel hand obs leer ist oder was hält
            int value = fact.value; // position in domain bsp: {frei, A, B}, 0 für frei
            precondition_to_operators[variable_id][value].push_back(op_id); // zu jedem Fakt (variable_id, value) / vorbedingung  schreib op_id
        }
    }
}

void GeneratorMarking::generate_applicable_ops(
    const vector<int> &state, vector<OperatorID> &applicable_ops) const { // state = [ 0 , 0 , 0 , 0 , 0 ] für h   a   b   fa  fb
    current_round += 1; 

    int num_variables = state.size(); 
    for (int variable_id = 0; variable_id < num_variables; ++variable_id) { // wie brauchen variable_id
        int value = state[variable_id]; // wert von dem Zusanstvariable
        const vector<int> &operators_here = precondition_to_operators[variable_id][value]; // liste der operatoren für den fakt

        for (int op_id : operators_here) {
            if (last_seen[op_id] != current_round) { // checkt ob der zuletzt in einer anderen Runde (beim vorherigen ausrugen) geändert? --> falls ja, alte zähler stand
                last_seen[op_id] = current_round; // zähler aktualiseiren
                count_precondition[op_id] = num_preconditions[op_id]; // Bedingungszähler frisch auf die Gesamtzahl seiner Vorbedingungen setzen.
            }
            // beim zweiten ausrunf in der selben ausruf if schleife wird üebrsprungen 

            count_precondition[op_id] -= 1; // zähler der vorbedingung wird runter gezählt

            if (count_precondition[op_id] == 0) { // falls der vorbedingugnzähler auf 0 erreicht, dann ist applipicbale
                applicable_ops.push_back(OperatorID(op_id));
            }
        }
    }

    for (OperatorID op : operators_without_preconditions) { // die op ohne vorbedingungen werden auch noch gepusht
        applicable_ops.push_back(op);
    }
}
}
