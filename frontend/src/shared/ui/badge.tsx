import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/src/shared/lib/utils';

const badgeVariants = cva(
    'inline-flex items-center rounded-sm px-1.5 py-0.5 text-[10px] uppercase font-bold tracking-widest transition-colors focus:outline-none focus:ring-1 focus:ring-ring focus:ring-offset-1 font-mono',
    {
        variants: {
            variant: {
                default: 'border border-transparent bg-primary text-primary-foreground hover:bg-primary/80',
                secondary: 'border border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80',
                destructive: 'border border-destructive bg-destructive/10 text-destructive hover:bg-destructive/20',
                outline: 'border border-border text-foreground',
                success: 'border border-success bg-success/10 text-success hover:bg-success/20',
                warning: 'border border-warning bg-warning/10 text-warning hover:bg-warning/20',
            },
        },
        defaultVariants: {
            variant: 'default',
        },
    },
);

export interface BadgeProps
    extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> { }

function Badge({ className, variant, ...props }: BadgeProps) {
    return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
