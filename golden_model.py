import turtle
import math

def draw_golden_model():
   # Setup the screen
   screen = turtle.Screen()
   screen.bgcolor("white")
   t = turtle.Turtle()
   t.speed(0)
   t.pensize(2)
   t.color("#1a73e8") # Google-blue style

   # The Golden Ratio constant
   phi = 1.61803398875
   
   # Draw the Golden Spiral (The Future Growth Path)
   # This represents the "All-in-One" expansion of an AI platform
   factor = 1.0
   for i in range(15):
       t.circle(factor, 90)
       factor *= phi

   # Move to draw the Model Number
   t.penup()
   t.goto(0, -100)
   t.color("#202124")
   t.pendown()
   
   # Write the Lucky Number
   t.write("Model: 1.618", align="center", font=("Arial", 24, "bold"))
   
   # Hide turtle and stay open
   t.hideturtle()
   screen.exitonclick()

if __name__ == "__main__":
   print("Generating the 1.618 Golden Ratio Model...")
   draw_golden_model()
