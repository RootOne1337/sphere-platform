import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/src/shared/lib/utils';

const buttonVariants = cva(
    'inline-flex items-center justify-center whitespace-nowrap rounded-sm text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 tracking-wide',
    {
        variants: {
            variant: {
                default: 'bg-primary text-primary-foreground hover:bg-primary/90 shadow-sm',
                destructive: 'bg-destructive text-destructive-foreground hover:bg-destructive/90 shadow-sm',
                outline: 'border border-border bg-background hover:bg-accent hover:text-accent-foreground',
                secondary: 'bg-secondary text-secondary-foreground hover:bg-secondary/80',
                ghost: 'hover:bg-accent hover:text-accent-foreground',
                link: 'text-primary underline-offset-4 hover:underline',
                noc: 'bg-[#1A1A1A] text-foreground border border-[#333] hover:border-primary hover:bg-[#222] uppercase text-[11px] font-bold tracking-widest', // Спец. стиль для NOC
            },
            size: {
                default: 'h-8 px-3 py-1', // Compact by default
                sm: 'h-7 px-2 text-xs',
                lg: 'h-9 px-6',
                icon: 'h-8 w-8',
                tiny: 'h-6 px-1.5 text-[10px]',
            },
        },
        defaultVariants: {
            variant: 'default',
            size: 'default',
        },
    },
);

export interface ButtonProps
    extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
    asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
    ({ className, variant, size, asChild = false, ...props }, ref) => {
        const Comp = asChild ? Slot : 'button';
        return (
            <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
        );
    },
);
Button.displayName = 'Button';

export { Button, buttonVariants };
