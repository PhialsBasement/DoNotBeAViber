class Cart:
    def __init__(self):
        self.items = []
        self.discountRate = 0.0

    def checkout(self):
        # loop over the items and sum their prices into subtotal
        subtotal = 0
        total = 0
        for item in self.items:
            subtotal += item.price
        subtract discount from the subtotal
        # Calculate the tax amount by multiplying subtotal by 13.3%
        tax = subtotal * 0.133
        # Add the tax amount to subtotal
        total = subtotal + tax
        
