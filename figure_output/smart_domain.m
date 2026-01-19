%% (3) Main Fig 3: Domain-wise overall SMART (grouped boxplots) by benchmark
clear; clc;
load('sim_smart.mat', 'scores','benchNames','domainNames','nUsers','nBench','nDomains','colors');

% Style
fontName = 'Helvetica';
axFontSize = 16;
labelFontSize = 17.6;
legFontSize = 16;

% Compute domain-wise per-user overall:
% overallGoal(u,b,d,s)=mean over dims; then mean over sessions -> userDomainOverall(u,b,d)
overallGoal = mean(scores, 5);                         % (u,b,d,s)
userDomainOverall = squeeze(mean(overallGoal, 4));     % (u,b,d)

% Build grouped boxplot with custom x positions:
% For each domain center at 1..nDomains, offset by benchmark
offset = [-0.25 0 0.25];  % A/B/C
positions = zeros(nDomains*nBench,1);
groupID   = zeros(nDomains*nBench*nUsers,1);
vals      = zeros(nDomains*nBench*nUsers,1);

idx = 0;
g = 0;
for d = 1:nDomains
    for b = 1:nBench
        g = g + 1;
        pos = d + offset(b);
        positions(g) = pos;

        y = userDomainOverall(:,b,d);  % 10 users

        for u = 1:nUsers
            idx = idx + 1;
            vals(idx) = y(u);
            groupID(idx) = g;          % group 1..9
        end
    end
end

fig = figure('Color','w','Position',[100 100 1000 520]);
ax  = axes(fig); hold(ax,'on');

boxplot(ax, vals, groupID, ...
    'Positions', positions, ...
    'Symbol', '', ...
    'Whisker', 1.5, ...
    'Widths', 0.18);

% Bold boxplot lines
set(findobj(ax,'Type','Line'), 'LineWidth', 2);

% Color each box by benchmark (identify by x-position)
hBox = findobj(ax, 'Tag', 'Box'); % reverse order
for i = 1:numel(hBox)
    xd = get(hBox(i), 'XData'); yd = get(hBox(i), 'YData');
    xCenter = mean(xd);

    % Find nearest group position
    [~, gIdx] = min(abs(positions - xCenter));

    % Map group -> benchmark: groups were created in order (d-major, b-minor)
    bIdx = mod(gIdx-1, nBench) + 1;

    patch('XData', xd, 'YData', yd, ...
        'FaceColor', colors(bIdx,:), 'FaceAlpha', 0.18, ...
        'EdgeColor', colors(bIdx,:), 'LineWidth', 2);
end

% Overlay user points with jitter around each group position
jitter = 0.04;
idx = 0;
for d = 1:nDomains
    for b = 1:nBench
        g = (d-1)*nBench + b;
        x0 = positions(g);
        y  = userDomainOverall(:,b,d);

        xj = x0 + (rand(size(y))-0.5)*2*jitter;
        plot(ax, xj, y, 'o', 'MarkerSize', 5.5, 'LineWidth', 1.2, 'Color', colors(b,:));

        idx = idx + 1;
    end
end

% Axes formatting
xlim(ax, [0.5 nDomains+0.5]);
ylim(ax, [0 5]);
yticks(ax, 0:1:5);

xticks(ax, 1:nDomains);
xticklabels(ax, domainNames);

ylabel(ax, 'Overall SMART Score', 'FontName',fontName, 'FontSize',labelFontSize, 'FontWeight','bold');

set(ax, 'FontName',fontName, 'FontSize',axFontSize, 'FontWeight','bold', 'LineWidth',1);
grid(ax, 'on');
box(ax, 'off');

% Legend (use dummy lines for clean legend)
hLeg = gobjects(1,nBench);
for b = 1:nBench
    hLeg(b) = plot(ax, NaN, NaN, '-', 'LineWidth', 3, 'Color', colors(b,:));
end

leg = legend(ax, hLeg, benchNames, 'Orientation','horizontal', 'NumColumns',3, 'Location','northoutside');
set(leg, 'Box','on', 'FontName',fontName, 'FontSize',legFontSize, 'FontWeight','bold');
