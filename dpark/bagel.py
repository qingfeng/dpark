import sys
import time
import logging
from pprint import pprint

logger = logging.getLogger("bagel")

class Vertex:
    def __init__(self, id, value, outEdges, active):
        self.id = id
        self.value = value
        self.outEdges = outEdges
        self.active = active
    def __repr__(self):
        return "<Vertex(%s, %s, %s)>" % (self.id, self.value, self.active)

class Message:
    def __init__(self, target_id, value):
        self.target_id = target_id
        self.value = value
    def __repr__(self):
        return "<Message(%s, %s)>" % (self.target_id, self.value)

class Edge:
    def __init__(self, target_id, value=0):
        self.target_id = target_id
        self.value = value
    def __repr__(self):
        return '<Edge(%s, %s)>' % (self.target_id, self.value)


class Combiner:
    def createCombiner(self, msg): raise NotImplementedError
    def mergeValue(self, combiner, msg): raise NotImplementedError
    def mergeCombiners(self, a, b): raise NotImplementedError

class Aggregator:
    def createAggregator(self, vert): raise NotImplementedError
    def mergeAggregator(self, a, b): raise NotImplementedError

class DefaultListCombiner(Combiner):
    def createCombiner(self, msg):
        return [msg]
    def mergeValue(self, combiner, msg):
        return combiner+[msg]
    def mergeCombiners(self, a, b):
        return a + b

class DefaultValueCombiner(Combiner):
    def createCombiner(self, msg):
        return msg.value
    def mergeValue(self, combiner, msg):
        return combiner + msg.value
    def mergeCombiners(self, a, b):
        return a + b


class Bagel:
    @classmethod
    def run(cls, ctx, verts, msgs, compute,
            combiner=DefaultValueCombiner(), aggregator=None,
            max_superstep=sys.maxint, numSplits=None):

        superstep = 0
        while superstep < max_superstep:
            logger.info("Starting superstep %d", superstep)
            start = time.time()
            aggregated = cls.agg(verts, aggregator) if aggregator else None
            combinedMsgs = msgs.combineByKey(combiner, numSplits)
            grouped = verts.groupWith(combinedMsgs, numSplits=numSplits)
            processed, numMsgs, numActiveVerts = cls.comp(ctx, grouped, 
                lambda v, ms: compute(v, ms, aggregated, superstep))
            logger.info("superstep %d took %.1f s", superstep, time.time()-start)

            noActivity = numMsgs == 0 and numActiveVerts == 0
            if noActivity:
                return processed.map(lambda (id, (vert, msgs)): vert)
            
            verts = processed.mapValue(lambda (vert, msgs): vert)
            msgs = processed.flatMap(lambda (id, (vert, msgs)):
                    [(m.target_id, m) for m in msgs])
            superstep += 1
            
        return verts.map(lambda (id, vert): vert)

    @classmethod
    def agg(cls, verts, aggregator):
        r = verts.map(lambda (id, vert): aggregator.createAggregator(vert))
        return r.reduce(aggregator.mergeAggregators)

    @classmethod
    def comp(cls, ctx, grouped, compute):
        numMsgs = ctx.accumulator(0)
        numActiveVerts = ctx.accumulator(0)
        def proc((vs, cs)):
            if not vs:
                return []
            newVert, newMsgs = compute(vs[0], cs)
            numMsgs.add(len(newMsgs))
            if newVert.active:
                numActiveVerts.add(1)
            return [(newVert, newMsgs)]
        processed = grouped.flatMapValue(proc).cache()
        # force evaluation of processed RDD for accurate performance measurements
        processed.count()
        return processed, numMsgs.value, numActiveVerts.value

    @classmethod
    def addAggregatorArg(cls, compute):
        def _(vert, messages, aggregator, superstep):
            return compute(vert, messages)
        return _
