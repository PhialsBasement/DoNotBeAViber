class Cart:
    def __init__(self):
        self.items = []
        self.discountRate = 0.0

    def checkout(self):
        subtotal = 0
        total = 0
        for item in self.items:
            subtotal += item.price
        subtotal -= self.discountRate * subtotal
        tax = subtotal * 0.133
        total = subtotal + tax
