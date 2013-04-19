'''Implements Sum-Product Algorithm over Factor Graphs'''
import sys
import copy
import inspect

from collections import defaultdict
from itertools import product as iter_product

'''
The example in SumProd.pdf has exactly the same shape 
as the cancer example:

(Note: arrows are from x1->x3, x2->x3, x3->x4 and x3->x5)

      x1      x2
       \      /
        \    /
         \  /
          x3
         /  \
        /    \
       /      \
      x4      x5


The equivalent Factor Graph is:


     fA        fB
     |          |
     x1---fC---x2
           |
     fD---x3---fE
     |          |
     x4         x5


fA(x1) = p(x1)
fB(x2) = p(x2)
fC(x1,x2,x3) = p(x3|x1,x2)
fD(x3,x4) = p(x4|x3)
fE(x3,x5) = p(x5|x3)

'''

class Node(object):

    def is_leaf(self):
        if len(self.neighbours) == 1:
            return True
        return False

    def send(self, message):
        recipient = message.destination
        print '%s ---> %s' % (
            self.name, recipient.name), message
        recipient.received_messages[
            self.name] = message

    def get_sent_messages(self):
        sent_messages = {}
        for neighbour in self.neighbours:
            if neighbour.received_messages.get(self.name):
                sent_messages[neighbour.name] = \
                    neighbour.received_messages.get(self.name)
        return sent_messages
        
    def message_report(self):
        '''
        List out all messages Node
        currently has received.
        '''
        print '------------------------------'
        print 'Messages at Node %s' % self.name
        print '------------------------------'
        for k, v in self.received_messages.iteritems():
            print '%s <-- Argspec:%s' % (v.source.name, v.argspec)
            v.list_factors()
        print '--'

    def get_target(self):
        '''
        A node can only send to a neighbour if
        it has not already sent to that neighbour
        and it has received messages from all other
        neighbours.
        '''
        neighbours = self.neighbours
        #if len(neighbours) - len(self.received_messages) > 1:
        #    return None
        needed_to_send = defaultdict(int)
        for target in neighbours:
            needed_to_send[target] = len(neighbours) - 1
        for _, message in self.received_messages.items():
            for target in neighbours:
                if message.source != target:
                    needed_to_send[target] -= 1
        for k, v in needed_to_send.items():
            if v == 0 and not self.name in k.received_messages:
                return k


class VariableNode(Node):
    
    def __init__(self, name, neighbours=[]):
        self.name = name
        self.neighbours = neighbours[:]
        self.received_messages = {}
        self.value = None

    def construct_message(self):
        target = self.get_target()
        message = make_variable_node_message(self, target)
        return message

    def __repr__(self):
        return '<VariableNode: %s>' % self.name

    def marginal(self, val, normalizer=1.0):
        '''
        The marginal function in a Variable
        Node is the product of all incoming
        messages. These should all be functions
        of this nodes variable.
        When any of the variables in the
        network are constrained we need to
        normalize.
        '''
        product = 1
        v = VariableNode(self.name)
        v.value = val
        for _, message in self.received_messages.iteritems():
            product *= message(v)
        return product / normalizer

    def reset(self):
        self.received_messages = {}


class FactorNode(Node):

    def __init__(self, name, func, neighbours=[]):
        self.name = name
        self.func = func
        self.neighbours = neighbours[:]
        self.received_messages = {}
        self.func.value = None
        self.cached_functions = []

    def construct_message(self):
        target = self.get_target()
        message = make_factor_node_message(self, target)
        return message

    def __repr__(self):
        return '<FactorNode %s %s(%s)>' % \
            (self.name,
             self.func.__name__,
             get_args(self.func))

    def marginal(self, val_dict):
        # The Joint marginal of the
        # neighbour variables of a factor
        # node is given by the product
        # of the incoming messages and the factor
        product = 1
        neighbours = self.neighbours
        for neighbour in neighbours:
            message = self.received_messages[neighbour.name]
            call_args = []
            for arg in get_args(message):
                call_args.append(val_dict[arg])
            if not call_args:
                call_args.append('dummy')
            product *= message(*call_args)
        # Finally we also need to multiply
        # by the factor itself
        call_args = []
        for arg in get_args(self.func):
            call_args.append(val_dict[arg])
        if not call_args:
            call_args.append('dummy')
        product *= self.func(*call_args)
        return product
    

    def add_evidence(self, node, value):
        '''
        Here we modify the factor function
        to return 0 whenever it is called
        with the observed variable having
        a value other than the observed value.
        '''
        args = get_args(self.func)
        pos = args.index(node.name)
        # Save the old func so that we
        # can remove the evidence later
        old_func = self.func
        self.cached_functions.insert(0, old_func)
        def evidence_func(*args):
            if args[pos].value != value:
                return 0
            return old_func(*args)
        evidence_func.argspec = args
        evidence_func.domains = old_func.domains
        self.func = evidence_func

    def reset(self):
        self.received_messages = {}
        if self.cached_functions:
            self.pop_evidence()

    def pop_evidence(self):
        self.func = self.cached_functions.pop()


class Message(object):

    def list_factors(self):
        print '---------------------------'
        print 'Factors in message %s -> %s' % (self.source.name, self.destination.name)
        print '---------------------------'
        for factor in self.factors:
            print factor

    def __call__(self, var):
        '''
        Evaluate the message as a function
        '''
        if getattr(self.func, '__name__', None) == 'unity':
            return 1
        assert isinstance(var, VariableNode)
        # Now check that the name of the
        # variable matches the argspec...
        #assert var.name == self.argspec[0]
        return self.func(var)


class VariableMessage(Message):

    def __init__(self, source, destination, factors, func):
        self.source = source
        self.destination = destination
        self.factors = factors
        self.argspec = get_args(func)
        self.func = func


    def __repr__(self):
        return '<V-Message from %s -> %s: %s factors (%s)>' % \
            (self.source.name, self.destination.name, 
             len(self.factors), self.argspec)


class FactorMessage(Message):

    def __init__(self, source, destination, factors, func):
        self.source = source
        self.destination = destination
        self.factors = factors
        self.func = func
        self.argspec = get_args(func)
        self.domains = func.domains

    def __repr__(self):
        return '<F-Message %s -> %s: ~(%s) %s factors.>' % \
            (self.source.name, self.destination.name,
             self.argspec,
             len(self.factors))


def connect(a, b):
    '''
    Make an edge between two nodes
    or between a source and several
    neighbours.
    '''
    if not isinstance(b, list):
        b = [b]
    for b_ in b:
        a.neighbours.append(b_)
        b_.neighbours.append(a)


def replace_var(f, var, val):
    arg_spec = get_args(f)
    pos = arg_spec.index(var)
    new_spec = arg_spec[:]
    new_spec.remove(var)
    
    def replaced(*args):
        template = arg_spec[:]
        v = VariableNode(name=var)
        v.value = val
        template[pos] = v
        call_args = template[:]
        for arg in args:
            arg_pos = call_args.index(arg.name)
            call_args[arg_pos] = arg
                
        return f(*call_args)

    replaced.argspec = new_spec
    return replaced
    

def eliminate_var(f, var):
    '''
    Given a function f return a new
    function which sums over the variable
    we want to eliminate
    '''
    arg_spec = get_args(f)
    pos = arg_spec.index(var)
    new_spec = arg_spec[:]
    new_spec.remove(var)

    def eliminated(*args):
        template = arg_spec[:]
        total = 0
        summation_vals = [True, False]
        call_args = template[:]
        for arg in args:
            arg_pos = template.index(arg.name)
            call_args[arg_pos] = arg
        for val in f.domains[var]:
            v = VariableNode(name=var)
            v.value = val
            call_args[pos] = v
            total += f(*call_args)
        return total

    eliminated.argspec = new_spec
    eliminated.domains = f.domains
    if not eliminated.domains:
        import ipdb; ipdb.set_trace()
    return eliminated


    


def make_not_sum_func(product_func, keep_var):
    '''
    Given a function with some set of
    arguments, and a single argument to keep,
    construct a new function only of the
    keep_var, summarized over all the other
    variables.
    '''
    args = get_args(product_func)
    new_func = copy.deepcopy(product_func)
    for arg in args:
        if arg != keep_var:
            new_func = eliminate_var(new_func, arg)
    return new_func


def make_factor_node_message(node, target_node):
    '''
    The rules for a factor node are:
    take the product of all the incoming
    messages (except for the destination
    node) and then take the sum over
    all the variables except for the
    destination variable.
    >>> def f(x1, x2, x3): pass
    >>> node = object()
    >>> node.func = f
    >>> target_node = object()
    >>> target_node.name = 'x2'
    >>> make_factor_node_message(node, target_node)
    '''

    if node.is_leaf():
        not_sum_func = make_not_sum_func(node.func, target_node.name)
        message = FactorMessage(node, target_node, [node.func], not_sum_func)
        return message

    args = set(get_args(node.func))
    
    # Compile list of factors for message
    factors = [node.func]
    
    # Now add the message that came from each
    # of the non-destination neighbours...
    neighbours = node.neighbours
    for neighbour in neighbours:
        if neighbour == target_node:
            continue
        # When we pass on a message, we unwrap
        # the original payload and wrap it
        # in new headers, this is purely
        # to verify the procedure is correct
        # according to usual nomenclature
        in_message = node.received_messages[neighbour.name]
        if in_message.destination != node:
            out_message = VariableMessage(neighbour, node, in_message.factors, in_message.func)
            out_message.argspec = in_message.argspec
        else:
            out_message = in_message
        factors.append(out_message)

    product_func = make_product_func(factors)
    not_sum_func = make_not_sum_func(product_func, target_node.name)
    message = FactorMessage(node, target_node, factors, not_sum_func)
    return message


def make_variable_node_message(node, target_node):
    '''
    To construct the message from 
    a variable node to a factor
    node we take the product of
    all messages received from
    neighbours except for any
    message received from the target.
    If the source node is a leaf node
    then send the unity function.
    '''
    if node.is_leaf():
        message = VariableMessage(
            node, target_node, [1], unity)
        return message
    factors = []
    neighbours = node.neighbours
    for neighbour in neighbours:
        if neighbour == target_node:
            continue
        factors.append(
            node.received_messages[neighbour.name])

    product_func = make_product_func(factors)
    message = VariableMessage(
        node, target_node, factors, product_func)
    return message

        
def get_args(func):
    '''
    Return the names of the arguments
    of a function as a list of strings.
    This is so that we can omit certain
    variables when we marginalize.
    Note that functions created by
    make_product_func do not return
    an argspec, so we add a argspec
    attribute at creation time.
    '''
    if hasattr(func, 'argspec'):
        return func.argspec
    return inspect.getargspec(func).args



def make_product_func(factors):
    '''
    Return a single callable from
    a list of factors which correctly
    applies the arguments to each 
    individual factor
    '''
    args_map = {}
    all_args = []
    domains = {}
    for factor in factors:
        #if factor == 1:
        #    continue
        args_map[factor] = get_args(factor)
        all_args += args_map[factor]
        if hasattr(factor, 'domains'):
            domains.update(factor.domains)
    args = list(set(all_args))

    def product_func(*args):
        arg_dict = dict([(a.name, a) for a in args])
        result = 1
        for factor in factors:
            #domains.update(factor.domains)
            # We need to build the correct argument
            # list to call this factor with.
            factor_args = []
            for arg in get_args(factor):
                if arg in arg_dict:
                    factor_args.append(arg_dict[arg])
            if not factor_args:
                # Since we always require
                # at least one argument we
                # insert a dummy argument
                # so that the unity function works.
                factor_args.append('dummy')
            result *= factor(*factor_args)
                
        return result

    product_func.argspec = args
    product_func.factors = factors
    product_func.domains = domains
    return product_func


def make_unity(argspec):
    def unity(x):
        return 1
    unity.argspec = argspec
    unity.__name__ = '1'
    return unity


def unity():
    return 1

def expand_args(args):
    if not args:
        return []
    return 


def dict_to_tuples(d):
    '''
    Convert a dict whose values
    are lists to a list of
    tuples of the key with
    each of the values
    '''
    retval = []
    for k, vals in d.iteritems():
        retval.append([(k, v) for v in vals])
    return retval
        

def expand_parameters(arg_vals):
    '''
    Given a list of args and values
    return a list of tuples
    containing all possible sequences
    of length n.
    '''
    arg_tuples = dict_to_tuples(arg_vals)
    return [dict(args) for args in iter_product(*arg_tuples)]


def add_evidence(node, value):
    '''
    Set a variable node to an observed value.
    Note that for now this is achieved
    by modifying the factor functions
    which this node is connected to.
    After updating the factor nodes
    we need to re-run the sum-product
    algorithm. We also need to normalize
    all marginal outcomes.
    '''
    neighbours = node.neighbours
    for factor_node in neighbours:
        if node.name in get_args(factor_node.func):
            factor_node.add_evidence(node, value)

    
            
            

class FactorGraph(object):

    def __init__(self, nodes):
        self.nodes = nodes
        # Cash the 
        self.domains = dict(
            x1 = [True, False],
            x2 = [True, False],
            x3 = [True, False],
            x4 = [True, False],
            x5 = [True, False])
        #for node in nodes:
        #    if isinstance(


    def reset(self):
        '''
        Reset all nodes back to their initial state.
        We should do this before or after adding
        or removing evidence.
        '''
        for node in self.nodes:
            node.reset()

    def get_leaves(self):
        return [node for node in self.nodes if node.is_leaf()]
        
    def get_eligible_senders(self):
        '''
        Return a list of nodes that is eligible to
        send messages at this round.
        Only nodes that have received
        messages from all but one neighbour
        may send at any round.
        '''
        eligible = []
        for node in self.nodes:
            if node.get_target():
                eligible.append(node)
        return eligible
    
    def propagate(self):
        '''
        This is the heart of the sum-product
        Message Passing Algorithm.
        '''
        step = 1
        while True:
            eligible_senders = self.get_eligible_senders()
            print 'Step: %s %s nodes can send.' % (step, len(eligible_senders))
            print [x.name for x in eligible_senders]
            if not eligible_senders:
                break
            for node in eligible_senders:
                message = node.construct_message()
                node.send(message)
            step += 1

        




























