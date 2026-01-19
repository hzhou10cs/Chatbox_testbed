%% (3) Figure 2: Score distribution (0/1/2) by benchmark (stacked % bars)
% MATLAB R2025a

clear; clc;
load('sim_proactivity.mat', 'T', 'benchNames', 'nBench');

% Style
fontName = 'Helvetica';
axFontSize = 16;
labelFontSize = 17.6;

% Use 3 distinct colors for scores 0/1/2 (keep consistent style family)
cBlue   = [0.0353, 0.5176, 0.8902];
cRed  = [0.9098, 0.2549, 0.0941];
cOrange = [0.9294, 0.6941, 0.1255];
cmap = [cRed; cBlue;  cOrange];

% Compute proportions
P = zeros(nBench, 3); % columns: score=0,1,2
for b = 1:nBench
    sel = (T.bench==b);
    scores = T.score(sel);
    P(b,1) = mean(scores==0);
    P(b,2) = mean(scores==1);
    P(b,3) = mean(scores==2);
end

fig = figure('Color','w', 'Position',[100 100 600 500]);
ax = axes(fig); hold(ax,'on');

gap = 1.4;  
x = (1:nBench) * gap; 

bh = bar(ax, x, 100*P, 'stacked', 'LineWidth', 1);
for k = 1:3
    bh(k).FaceColor = cmap(k,:);
    bh(k).BarWidth = 0.6;
end

xticks(ax, x);
xticklabels(ax, benchNames);
xlim(ax, [x(1)-0.8, x(end)+0.8]);

ylim(ax, [0 100]);

ylabel(ax, 'Percentage of Rounds (%)', 'FontName',fontName, 'FontSize',labelFontSize, 'FontWeight','bold');

set(ax, 'FontName',fontName, 'FontSize',axFontSize, 'FontWeight','bold', 'LineWidth',1);
grid(ax, 'on');
box(ax, 'off');

leg = legend(ax, {'Score=0','Score=1','Score=2'}, 'Location','northoutside', 'Orientation','horizontal');
set(leg, 'Box','on', 'FontName',fontName, 'FontSize',axFontSize, 'FontWeight','bold');
