import logging

LOGGER = logging.getLogger("store")


class OrderStore:
    def __init__(self, dbConn):
        self.dbConn = dbConn
        self.pendingOrders = []
        self.failedCount = 0

    def addOrder(self, order):
        self.pendingOrders.append(order)
        LOGGER.debug("queued order %s", order.orderId)

    def flushOrders(self):
        pass  # cursor target: line 17
